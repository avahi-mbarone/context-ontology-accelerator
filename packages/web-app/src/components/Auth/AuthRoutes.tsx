// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import React from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { LoginPage } from "@pages/LoginPage";
import { AuthenticatePage } from "@pages/AuthenticatePage";

interface AuthRoutesProps {
  title: string;
}

export const AuthRoutes: React.FC<AuthRoutesProps> = ({ title }) => (
  <Routes>
    <Route path="/login" element={<LoginPage title={title} />} />
    <Route path="/authenticate" element={<AuthenticatePage title={title} />} />
    <Route path="*" element={<Navigate to="/login" />} />
  </Routes>
);
