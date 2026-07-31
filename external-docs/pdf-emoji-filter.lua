-- pdf-emoji-filter.lua
-- Renders special Unicode characters using LaTeX commands for PDF output

function Str(elem)
  local result = {}
  local current = ""

  for _, code in utf8.codes(elem.text) do
    if code == 0x2192 then -- →
      if current ~= "" then
        table.insert(result, pandoc.Str(current))
        current = ""
      end
      table.insert(result, pandoc.RawInline("latex", "\\arrowsym{}"))
    elseif code == 0x2705 then -- ✅
      if current ~= "" then
        table.insert(result, pandoc.Str(current))
        current = ""
      end
      table.insert(result, pandoc.RawInline("latex", "\\checksym{}"))
    elseif code == 0x274C then -- ❌
      if current ~= "" then
        table.insert(result, pandoc.Str(current))
        current = ""
      end
      table.insert(result, pandoc.RawInline("latex", "\\crosssym{}"))
    else
      current = current .. utf8.char(code)
    end
  end

  if current ~= "" then
    table.insert(result, pandoc.Str(current))
  end

  if #result == 0 then
    return nil
  elseif #result == 1 then
    return result[1]
  elseif #result > 1 then
    return result
  end
end
