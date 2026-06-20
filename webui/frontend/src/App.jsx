import React, { useState, useRef, useEffect } from "react";
import { loadBuild, getArchetype, getClassTree, streamChat } from "./api.js";

const TABS = ["Build", "Archetype", "Class Tree", "Chat", "Settings"];

export default function App() {
  const [tab, setTab] = useState("Build");
  const [apiKey, setApiKeyState] = useState(() => localStorage.getItem("anthropicKey") || "");
  const setApiKey = (v) => {
    const k = (v || "").trim();
    setApiKeyState(k);
    if (k) localStorage.setItem("anthropicKey", k);
    else localStorage.removeItem("anthropicKey");
  };
  return (
    <div className="app">
      <header>
        <h1>PoE2 Build Lab</h1>
        <nav>
          {TABS.map((t) => (
            <button key={t} className={t === tab ? "tab active" : "tab"} onClick={() => setTab(t)}>
              {t}
            </button>
          ))}
        </nav>
      </header>
      <main>
        {tab === "Build" && <BuildPanel />}
        {tab === "Archetype" && <ArchetypePanel />}
        {tab === "Class Tree" && <ClassTreePanel />}
        {tab === "Chat" && <ChatPanel apiKey={apiKey} goSettings={() => setTab("Settings")} />}
        {tab === "Settings" && <SettingsPanel apiKey={apiKey} onSave={setApiKey} />}
      </main>
    </div>
  );
}

function SettingsPanel({ apiKey, onSave }) {
  const [val, setVal] = useState(apiKey);
  const [reveal, setReveal] = useState(false);
  return (
    <section className="settings">
      <h3>Anthropic API key</h3>
      <p className="muted">
        Powers the Chat tab (model: <code>claude-sonnet-4-6</code>). Stored only in this
        browser (localStorage) and sent to your local backend with each chat request —
        never written to the repo or logged. The structured panels don't need it.
      </p>
      <div className="loader">
        <input
          type={reveal ? "text" : "password"}
          placeholder="sk-ant-…"
          value={val}
          onChange={(e) => setVal(e.target.value)}
        />
        <button className="ghost" onClick={() => setReveal((r) => !r)}>{reveal ? "Hide" : "Show"}</button>
      </div>
      <div className="settings-actions">
        <button onClick={() => onSave(val)} disabled={!val.trim() || val.trim() === apiKey}>Save key</button>
        <button className="ghost" onClick={() => { setVal(""); onSave(""); }} disabled={!apiKey}>Clear</button>
        <span className={apiKey ? "keystate ok" : "keystate"}>{apiKey ? "✓ key saved" : "no key set"}</span>
      </div>
    </section>
  );
}

function useAsync() {
  const [state, setState] = useState({ loading: false, data: null, error: null });
  const run = async (fn) => {
    setState({ loading: true, data: null, error: null });
    try {
      const data = await fn();
      setState({ loading: false, data: data.error ? null : data, error: data.error || null });
    } catch (e) {
      setState({ loading: false, data: null, error: String(e) });
    }
  };
  return [state, run];
}

// --- shared bits --------------------------------------------------------- //

function Bucket({ title, items, kind }) {
  if (!items || !items.length) return null;
  return (
    <div className="bucket">
      <h4 className={kind}>{title}</h4>
      <ul>
        {items.map((i) => (
          <li key={i.name}>
            <span className="row-name">
              {i.name}
              {i.type ? <em className="tag">{i.type}</em> : null}
            </span>
            {i.pct != null && (
              <span className="bar">
                <span className="fill" style={{ width: `${i.pct}%` }} />
                <span className="pct">{i.pct}%</span>
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Asc({ list }) {
  if (!list?.length) return null;
  return (
    <div className="chips">
      {list.map((a) => (
        <span className="chip" key={a.name}>{a.name} <b>{a.pct}%</b></span>
      ))}
    </div>
  );
}

// --- Build panel --------------------------------------------------------- //

function BuildPanel() {
  const [code, setCode] = useState("");
  const [s, run] = useAsync();
  const b = s.data;
  const stat = (name) => b?.stats.find((x) => x.stat === name)?.value;
  const KEY = [
    ["Life", "Life"], ["Energy Shield", "EnergyShield"], ["Total EHP", "TotalEHP"],
    ["Fire Res", "FireResist"], ["Cold Res", "ColdResist"], ["Lightning Res", "LightningResist"],
    ["Chaos Res", "ChaosResist"], ["Combined DPS", "CombinedDPS"],
  ];
  return (
    <section>
      <div className="loader">
        <input
          placeholder="PoB export code, pobb.in link, or pob_code.txt"
          value={code}
          onChange={(e) => setCode(e.target.value)}
        />
        <button onClick={() => run(() => loadBuild(code))} disabled={s.loading || !code}>
          {s.loading ? "Loading…" : "Load build"}
        </button>
      </div>
      {s.error && <p className="error">{s.error}</p>}
      {b && (
        <>
          <div className="chips">
            <span className="chip">{b.summary.class} — {b.summary.ascendancy}</span>
            <span className="chip">Level {b.summary.level}</span>
            <span className="chip">{b.summary.items} items</span>
            <span className="chip">{b.summary.skill_groups} skills</span>
          </div>

          <div className="grid stats">
            {KEY.map(([label, k]) => (
              <div className="stat" key={k}>
                <span className="label">{label}</span>
                <span className="value">{fmt(stat(k))}</span>
              </div>
            ))}
          </div>

          <h3>Defenses</h3>
          <ul className="defenses">
            {b.defenses.map((d, i) => (
              <li key={i} className={`sev-${d.severity}`}>{d.message}</li>
            ))}
          </ul>

          <h3>Skills</h3>
          <div className="grid cards">
            {b.skills.filter((g) => g.active_skill && g.active_skill !== "").map((g, i) => (
              <div className="card" key={i}>
                <b>{g.active_skill}</b>
                <div className="supports">
                  {g.gems.filter((gm) => gm.is_support).map((gm) => (
                    <span className="mini" key={gm.name}>{gm.name}</span>
                  ))}
                </div>
              </div>
            ))}
          </div>

          <h3>Items</h3>
          <div className="grid cards">
            {b.items.map((it, i) => (
              <div className="card" key={i}>
                <b className={`rar-${it.rarity?.toLowerCase()}`}>{it.name}</b>
                <small>{it.slot} · {it.base_type}</small>
                <ul className="mods">{it.mods.map((m, j) => <li key={j}>{m}</li>)}</ul>
              </div>
            ))}
          </div>
        </>
      )}
    </section>
  );
}

// --- Archetype panel ----------------------------------------------------- //

function ArchetypePanel() {
  const [skill, setSkill] = useState("Twister");
  const [s, run] = useAsync();
  const a = s.data;
  return (
    <section>
      <div className="loader">
        <input value={skill} onChange={(e) => setSkill(e.target.value)} placeholder="Skill, e.g. Twister" />
        <button onClick={() => run(() => getArchetype(skill))} disabled={s.loading || !skill}>
          {s.loading ? "Analyzing…" : "Analyze"}
        </button>
      </div>
      {s.loading && <p className="muted">Fetching cohort builds — this can take a few seconds.</p>}
      {s.error && <p className="error">{s.error}</p>}
      {a && a.cohort_size === 0 && <p className="muted">{a.note}</p>}
      {a && a.cohort_size > 0 && (
        <>
          <p className="muted">Cohort: {a.cohort_size} builds · core ≥ {a.core_threshold_pct}%</p>
          <Asc list={a.ascendancies} />

          <div className="cols">
            <Bucket title="Core skills" items={a.core_skills} kind="core" />
            <Bucket title="Tech skills" items={a.tech_skills} kind="tech" />
          </div>

          {a.support_breakdown && (
            <>
              <h3>Support gems per skill</h3>
              <div className="grid cards">
                {Object.entries(a.support_breakdown).map(([sk, d]) => (
                  <div className="card" key={sk}>
                    <b>{sk}</b> <small>({d.builds_seen} builds)</small>
                    <Bucket title="Core" items={d.core_supports} kind="core" />
                    <Bucket title="Tech" items={d.tech_supports} kind="tech" />
                  </div>
                ))}
              </div>
            </>
          )}

          {a.passive_tree && (
            <>
              <h3>Passive tree</h3>
              <div className="cols">
                <Bucket title="Core nodes" items={a.passive_tree.core_nodes} kind="core" />
                <Bucket title="Tech nodes" items={a.passive_tree.tech_nodes} kind="tech" />
              </div>
            </>
          )}

          <h3>Gear priorities</h3>
          <ul className="gear">
            {a.gear_priorities.map((g, i) => (
              <li key={i}><span className={`prio prio-${g.priority}`}>{g.priority}</span> <b>{g.stat}</b> — {g.why}</li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

// --- Class tree panel ---------------------------------------------------- //

function ClassTreePanel() {
  const [cls, setCls] = useState("Huntress");
  const [s, run] = useAsync();
  const c = s.data;
  return (
    <section>
      <div className="loader">
        <input value={cls} onChange={(e) => setCls(e.target.value)} placeholder="Class, e.g. Huntress" />
        <button onClick={() => run(() => getClassTree(cls))} disabled={s.loading || !cls}>
          {s.loading ? "Scanning…" : "Analyze"}
        </button>
      </div>
      {s.loading && <p className="muted">Scanning the ladder and fetching builds — this can take a bit.</p>}
      {s.error && <p className="error">{s.error}</p>}
      {c && c.cohort_size === 0 && <p className="muted">{c.note}</p>}
      {c && c.cohort_size > 0 && (
        <>
          <p className="muted">Cohort: {c.cohort_size} builds · core ≥ {c.core_threshold_pct}%</p>
          <Asc list={c.ascendancies} />
          <div className="cols">
            <Bucket title="Core nodes" items={c.core_nodes} kind="core" />
            <Bucket title="Tech nodes" items={c.tech_nodes} kind="tech" />
          </div>
        </>
      )}
    </section>
  );
}

// --- Chat panel ---------------------------------------------------------- //

function ChatPanel({ apiKey, goSettings }) {
  const [msgs, setMsgs] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef(null);
  useEffect(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), [msgs]);

  const send = async () => {
    if (!input.trim() || busy) return;
    const history = [...msgs, { role: "user", content: input.trim() }];
    setMsgs([...history, { role: "assistant", content: "", tools: [] }]);
    setInput("");
    setBusy(true);
    try {
      await streamChat(history, (ev) => {
        setMsgs((cur) => {
          const next = [...cur];
          const a = next[next.length - 1];
          if (ev.type === "text") a.content += ev.text;
          else if (ev.type === "tool") a.tools = [...(a.tools || []), ev.name];
          else if (ev.type === "error") a.content += `\n⚠️ ${ev.message}`;
          return next;
        });
      }, apiKey);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="chat">
      {!apiKey && (
        <div className="banner">
          No API key set. <button className="link" onClick={goSettings}>Add one in Settings</button> to enable chat.
        </div>
      )}
      <div className="messages">
        {msgs.length === 0 && (
          <p className="muted">Ask anything — e.g. "what are the core elements of a Twister build?"
            {apiKey ? " Runs on claude-sonnet-4-6." : ""}</p>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            {m.tools?.length ? <div className="toolrow">🔧 {m.tools.join(", ")}</div> : null}
            <div className="bubble">{m.content || (busy && i === msgs.length - 1 ? "…" : "")}</div>
          </div>
        ))}
        <div ref={endRef} />
      </div>
      <div className="composer">
        <textarea
          value={input}
          placeholder="Ask about a build, archetype, or mechanic…"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
        />
        <button onClick={send} disabled={busy || !input.trim()}>{busy ? "…" : "Send"}</button>
      </div>
    </section>
  );
}

function fmt(v) {
  if (v == null) return "—";
  const n = Number(v);
  if (Number.isNaN(n)) return v;
  return n >= 1000 ? Math.round(n).toLocaleString() : Math.round(n * 10) / 10;
}
