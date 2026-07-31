// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Utility for bundling Python Lambda code from monorepo `src/` layout packages.
 *
 * Handles:
 *   - Flattening `src/` layout so modules are importable at the Lambda root
 *   - Merging multiple source directories (e.g. package + shared lib)
 *   - Installing pip dependencies into the asset
 *   - Local bundling first (no Docker needed), with Docker fallback
 */
import { execSync } from "child_process";
import * as crypto from "crypto";
import * as fs from "fs";
import * as cdk from "aws-cdk-lib";
import * as lambda from "aws-cdk-lib/aws-lambda";
import { Paths } from "../paths";

export interface PythonBundlingOptions {
  /** Absolute paths to `src/` directories whose contents are copied to the asset root. */
  readonly srcDirs: string[];
  /**
   * How to install pip dependencies. Provide exactly one of:
   *   - `requirementsFile` — path to a `requirements.txt`
   *   - `pipDeps` — explicit list of package names
   *
   * If neither is provided, no pip install step runs.
   */
  readonly requirementsFile?: string;
  readonly pipDeps?: string[];
  /**
   * Target Lambda architecture. Determines the pip platform tag.
   * @default "x86_64"
   */
  readonly architecture?: "x86_64" | "arm64";
}

/**
 * Resolve the local pip command. macOS often has `pip3` but not `pip` (or
 * has an Xcode stub at /usr/local/bin/pip that fails with xcode-select).
 * Docker bundling always uses `pip` (available in the Python container).
 */
function resolvePipCommand(): string {
  try {
    execSync("pip --version", { stdio: "pipe" });
    return "pip";
  } catch {
    try {
      execSync("pip3 --version", { stdio: "pipe" });
      return "pip3";
    } catch {
      return "pip";
    }
  }
}

/**
 * Returns a bundled `lambda.Code` that merges one or more Python `src/`
 * directories and installs pip dependencies.
 *
 * @example
 * ```ts
 * // Using a requirements file:
 * bundlePython({
 *   srcDirs: [Paths.controlPlaneSrc, fromRoot("libs/common/src")],
 *   requirementsFile: fromRoot("packages/control-plane/requirements.txt"),
 * });
 *
 * // Using an explicit list:
 * bundlePython({
 *   srcDirs: [Paths.controlPlaneSrc, fromRoot("libs/common/src")],
 *   pipDeps: ["pydantic", "structlog"],
 * });
 * ```
 */
export function bundlePython(opts: PythonBundlingOptions): lambda.Code {
  // Compute a stable hash from only the files that matter for this Lambda.
  const assetHash = _computeSourceHash(opts.srcDirs, opts.requirementsFile);

  // Normalize all source paths to forward slashes for Docker compatibility
  const srcDirs = opts.srcDirs.map((d) => d.replace(/\\/g, "/"));
  const copies = srcDirs.map((d) => `cp -r ${d}/* /asset-output/`);
  const platform =
    opts.architecture === "arm64"
      ? "manylinux2014_aarch64"
      : "manylinux2014_x86_64";

  // Packages provided by the Lambda runtime — must not be overridden.
  const runtimePkgs = [
    "boto3",
    "botocore",
    "urllib3",
    "s3transfer",
    "jmespath",
  ];
  const cleanup = runtimePkgs
    .map(
      (p) =>
        `rm -rf /asset-output/${p} /asset-output/${p.replace("-", "_")}*dist-info`,
    )
    .join(" && ");

  const localPip = resolvePipCommand();
  const pipFlags = `--target /asset-output --platform ${platform} --only-binary=:all: --python-version 3.12 -q --no-cache-dir --disable-pip-version-check`;

  let localPipSteps: string[] = [];
  let dockerPipSteps: string[] = [];
  if (opts.requirementsFile) {
    const reqFile = opts.requirementsFile.replace(/\\/g, "/");
    localPipSteps = [`${localPip} install -r ${reqFile} ${pipFlags}`, cleanup];
    dockerPipSteps = [`pip install -r ${reqFile} ${pipFlags}`, cleanup];
  } else if (opts.pipDeps?.length) {
    const deps = opts.pipDeps.map((d) => `'${d}'`).join(" ");
    localPipSteps = [`${localPip} install ${pipFlags} ${deps}`, cleanup];
    dockerPipSteps = [`pip install ${pipFlags} ${deps}`, cleanup];
  }

  const localSteps = [...copies, ...localPipSteps];
  const bundleCmd = localSteps.join(" && ");

  const dockerSteps = [...copies, ...dockerPipSteps];
  const rootForward = Paths.root.replace(/\\/g, "/");
  const dockerCmd = dockerSteps
    .join(" && ")
    .replace(new RegExp(escapeRegExp(rootForward), "g"), "/asset-input");

  return lambda.Code.fromAsset(Paths.root, {
    assetHashType: cdk.AssetHashType.CUSTOM,
    assetHash,
    bundling: {
      image: lambda.Runtime.PYTHON_3_12.bundlingImage,
      command: ["bash", "-c", dockerCmd],
      local: {
        tryBundle(_outputDir: string) {
          // Skip local bundling on Windows — always use Docker.
          // Local bundling requires Unix commands (cp, rm) that don't exist in CMD.
          if (process.platform === "win32") {
            return false;
          }
          try {
            execSync(bundleCmd.replace(/\/asset-output/g, _outputDir), {
              stdio: "inherit",
            });
            return true;
          } catch {
            return false;
          }
        },
      },
    },
  });
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Compute a stable SHA-256 hash from only the source files and requirements
 * that actually affect this Lambda bundle. Used as a custom CDK asset hash
 * so that unrelated repo changes (test outputs, coverage files, etc.) don't
 * trigger unnecessary re-bundles.
 *
 * On Linux/macOS: uses `find | sort | xargs sha256sum` (preserves existing hashes).
 * On Windows: uses Node.js fs (quiet, no shell noise).
 */
function _computeSourceHash(
  srcDirs: string[],
  requirementsFile?: string,
): string {
  const hash = crypto.createHash("sha256");
  for (const dir of srcDirs) {
    try {
      if (process.platform === "win32") {
        const normalizedDir = dir.replace(/\\/g, "/");
        const files = _collectPyFiles(normalizedDir).sort();
        for (const file of files) {
          const fileHash = crypto
            .createHash("sha256")
            .update(fs.readFileSync(file))
            .digest("hex");
          hash.update(`${fileHash}  ${file}\n`);
        }
      } else {
        const out = execSync(
          `find ${dir} -type f -name "*.py" | sort | xargs sha256sum 2>/dev/null || true`,
          { encoding: "utf-8", stdio: ["pipe", "pipe", "pipe"] },
        );
        hash.update(out);
      }
    } catch {
      // Directory may not exist yet — ignore
    }
  }
  if (requirementsFile && fs.existsSync(requirementsFile)) {
    hash.update(fs.readFileSync(requirementsFile));
  }
  return hash.digest("hex");
}

/** Recursively collect all .py file paths in a directory. */
function _collectPyFiles(dir: string): string[] {
  if (!fs.existsSync(dir)) return [];
  const results: string[] = [];
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    const fullPath = `${dir}/${entry.name}`;
    if (entry.isDirectory()) {
      results.push(..._collectPyFiles(fullPath));
    } else if (entry.isFile() && entry.name.endsWith(".py")) {
      results.push(fullPath);
    }
  }
  return results;
}
