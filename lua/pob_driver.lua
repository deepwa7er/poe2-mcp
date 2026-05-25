-- P3 headless Path of Building driver: line-delimited JSON over stdio.
-- See docs/p3-headless-pob.md.
--
-- Invoked as:  luajit <thisfile> <POB_ROOT>   with cwd = <POB_ROOT>/src
--
-- Protocol — one JSON object per line in, one per line out. Every response echoes
-- the request `id` and carries `ok` (boolean); failures add `error`.
--   {"id":1,"cmd":"ping"}                          -> {"id":1,"ok":true,"pong":true}
--   {"id":2,"cmd":"load","xml":"<PathOfBuilding>"} -> {"id":2,"ok":true}
--   {"id":3,"cmd":"set_config","overrides":{"conditionEnemyShocked":true}} -> {"ok":true}
--   {"id":4,"cmd":"select_skill","group":2}        -> {"ok":true}
--   {"id":5,"cmd":"get_output","stats":["TotalDPS","Life"]} -> {...,"output":{...}}
--   {"id":6,"cmd":"shutdown"}                       -> {"ok":true}
--
-- A bad build or command yields {"ok":false,"error":...} and never kills the daemon.

local POB_ROOT = arg[1] or error("usage: luajit pob_driver.lua <POB_ROOT> (cwd must be <POB_ROOT>/src)")

-- Keep stdout pristine for JSON: route PoB's console/init prints to stderr.
print = function(...)
	local t = {}
	for i = 1, select("#", ...) do t[i] = tostring((select(i, ...))) end
	io.stderr:write(table.concat(t, "\t"), "\n")
end

package.path = POB_ROOT .. "/runtime/lua/?.lua;" .. POB_ROOT .. "/runtime/lua/?/init.lua;" .. package.path
local json = require("dkjson")

dofile("HeadlessWrapper.lua") -- defines globals: build, loadBuildFromXML, runCallback, ...

local function recalc()
	build.configTab:BuildModList()
	build.buildFlag = true
	runCallback("OnFrame")
end

local DEFAULT_STATS = {
	"TotalDPS", "CombinedDPS", "FullDPS", "Life", "EnergyShield", "Mana",
	"ManaUnreserved", "Spirit", "SpiritUnreserved", "CritChance",
	"PowerChargesMax", "FrenzyChargesMax",
}

local function collect(stats)
	local out = {}
	local mo = (build and build.calcsTab and build.calcsTab.mainOutput) or {}
	for _, k in ipairs(stats or DEFAULT_STATS) do
		local v = mo[k]
		local t = type(v)
		if t == "number" or t == "string" or t == "boolean" then
			out[k] = v
		end
	end
	return out
end

local handlers = {}

function handlers.ping()
	return { pong = true }
end

function handlers.load(req)
	if type(req.xml) ~= "string" then error("load requires an 'xml' string") end
	loadBuildFromXML(req.xml, req.name or "engine")
	-- Surface tree-version drift: the build's tree version vs PoB's bundled data.
	return {
		tree_version = build and build.spec and build.spec.treeVersion,
		pob_tree_version = latestTreeVersion,
	}
end

function handlers.set_config(req)
	for k, v in pairs(req.overrides or {}) do
		build.configTab.input[k] = v
	end
	recalc()
	return {}
end

function handlers.select_skill(req)
	if req.group then
		build.mainSocketGroup = req.group
		recalc()
	end
	return {}
end

function handlers.list_skills()
	local out = {}
	local sgl = (build.skillsTab and build.skillsTab.socketGroupList) or {}
	for i, sg in ipairs(sgl) do
		local skill
		local dsl = sg.displaySkillList
		if dsl and #dsl > 0 then
			local active = dsl[math.min(sg.mainActiveSkill or 1, #dsl)]
			local ge = active and active.activeEffect and active.activeEffect.grantedEffect
			skill = ge and ge.name
		end
		out[i] = {
			index = i,
			label = sg.label,
			skill = skill or sg.displayLabel,
			enabled = sg.enabled ~= false,
			is_main = (i == build.mainSocketGroup),
		}
	end
	return { skills = out }
end

function handlers.get_output(req)
	return { output = collect(req.stats) }
end

function handlers.shutdown()
	return { _shutdown = true }
end

local function respond(t)
	io.write(json.encode(t), "\n")
	io.stdout:flush()
end

for line in io.lines() do
	if line ~= "" then
		local req, _, derr = json.decode(line)
		if type(req) ~= "table" then
			respond({ ok = false, error = "bad json: " .. tostring(derr) })
		else
			local h = handlers[req.cmd]
			if not h then
				respond({ id = req.id, ok = false, error = "unknown cmd: " .. tostring(req.cmd) })
			else
				local ok, res = pcall(h, req)
				if ok then
					res = res or {}
					res.id = req.id
					res.ok = true
					local shutdown = res._shutdown
					res._shutdown = nil
					respond(res)
					if shutdown then break end
				else
					respond({ id = req.id, ok = false, error = tostring(res) })
				end
			end
		end
	end
end
