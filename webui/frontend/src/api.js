const BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

export async function loadBuild(code) {
  const r = await fetch(`${BASE}/api/load`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
  return r.json();
}

export async function getArchetype(skill, supportBuilds = 12) {
  const q = new URLSearchParams({ skill, support_builds: supportBuilds });
  return (await fetch(`${BASE}/api/archetype?${q}`)).json();
}

export async function getClassTree(className, scanLimit = 80) {
  const q = new URLSearchParams({ class_name: className, scan_limit: scanLimit });
  return (await fetch(`${BASE}/api/class-tree?${q}`)).json();
}

// Streams chat over SSE. onEvent({type, ...}) fires per server event.
export async function streamChat(messages, onEvent, apiKey) {
  const resp = await fetch(`${BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages, api_key: apiKey || null }),
  });
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const chunks = buf.split("\n\n");
    buf = chunks.pop(); // keep partial
    for (const chunk of chunks) {
      let event = "message", data = "";
      for (const line of chunk.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (data) onEvent({ type: event, ...JSON.parse(data) });
    }
  }
}
