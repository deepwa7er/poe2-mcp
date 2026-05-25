-- Pure-Lua fallback for the `lua-utf8` (luautf8) native module that PoB expects
-- from its host runtime. It lets headless PoB boot without building luautf8.so.
--
-- This implementation is BYTE-oriented (ASCII-correct, not codepoint-correct).
-- That is acceptable here because our headless path only *loads* a build and
-- *reads* computed stats — it never edits or measures display text, so PoB's
-- handful of utf8.* call sites are effectively unused at runtime. For full
-- multibyte correctness, install the real luautf8 (see docs/p3-headless-pob.md);
-- setup_pob.py only drops this fallback in when no real luautf8 is found.
local s = string
local M = setmetatable({}, { __index = s })

M.len, M.sub, M.byte, M.char = s.len, s.sub, s.byte, s.char
M.reverse, M.upper, M.lower, M.rep = s.reverse, s.upper, s.lower, s.rep
M.find, M.match, M.gmatch, M.gsub, M.format = s.find, s.match, s.gmatch, s.gsub, s.format

function M.next(str, i)
	i = (i or 0) + 1
	if i > #str then return nil end
	return i, s.byte(str, i)
end

function M.charpos(str, i)
	i = i or 1
	return i, s.byte(str, i)
end

function M.offset(str, n) return n end
function M.escape(p) return p end
function M.width(str) return #str end

function M.ncasecmp(a, b)
	a, b = a:lower(), b:lower()
	if a == b then return 0 end
	return a < b and -1 or 1
end

return M
