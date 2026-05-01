import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import "./styles.css";

type ChatRole = "user" | "teak" | "system";

interface TerminalPayload {
  data: string;
}

interface BrainFile {
  name: string;
  path: string;
  content: string;
}

interface ProjectSnapshot {
  project_root: string;
  brain_exists: boolean;
  brain_files: BrainFile[];
  status: string;
}

interface GitSnapshot {
  clean: boolean;
  output: string;
}

const app = document.querySelector<HTMLDivElement>("#app");

if (!app) {
  throw new Error("missing #app mount");
}

app.innerHTML = `
  <main class="shell" style="--left-pane: 48%">
    <section class="pane chat-pane" aria-label="Teak chat">
      <header class="topbar">
        <div class="brand">
          <span class="mark">T</span>
          <div>
            <h1>Teak</h1>
            <p id="projectStatus">No project loaded</p>
          </div>
        </div>
        <button id="loadProject" class="button primary" type="button">Load</button>
      </header>

      <div class="project-row">
        <label for="projectPath">Project</label>
        <input id="projectPath" class="path-input" spellcheck="false" />
      </div>

      <div id="chatMessages" class="chat-messages" aria-live="polite"></div>

      <form id="chatForm" class="composer">
        <div class="mode-row" role="group" aria-label="Teak run mode">
          <button class="segment active" id="reviewMode" type="button">Review</button>
          <button class="segment" id="autoMode" type="button">Auto</button>
        </div>
        <textarea
          id="chatInput"
          rows="3"
          placeholder="Describe the coding task..."
        ></textarea>
        <div class="composer-actions">
          <button id="statusButton" class="button" type="button">Status</button>
          <button id="sendButton" class="button primary" type="submit">Send</button>
        </div>
      </form>
    </section>

    <div id="splitter" class="splitter" role="separator" aria-orientation="vertical"></div>

    <section class="pane terminal-pane" aria-label="Terminal">
      <header class="terminal-bar">
        <div>
          <h2>Terminal</h2>
          <p id="terminalStatus">Stopped</p>
        </div>
        <div class="terminal-actions">
          <button id="restartTerminal" class="button ghost" type="button">Restart</button>
        </div>
      </header>
      <div id="terminal" class="terminal-host"></div>
    </section>
  </main>
`;

const root = document.querySelector<HTMLElement>(".shell")!;
const projectInput = byId<HTMLInputElement>("projectPath");
const projectStatus = byId<HTMLElement>("projectStatus");
const terminalStatus = byId<HTMLElement>("terminalStatus");
const chatMessages = byId<HTMLDivElement>("chatMessages");
const chatForm = byId<HTMLFormElement>("chatForm");
const chatInput = byId<HTMLTextAreaElement>("chatInput");
const terminalHost = byId<HTMLDivElement>("terminal");
const loadProjectButton = byId<HTMLButtonElement>("loadProject");
const restartTerminalButton = byId<HTMLButtonElement>("restartTerminal");
const statusButton = byId<HTMLButtonElement>("statusButton");
const sendButton = byId<HTMLButtonElement>("sendButton");
const reviewModeButton = byId<HTMLButtonElement>("reviewMode");
const autoModeButton = byId<HTMLButtonElement>("autoMode");
const splitter = byId<HTMLDivElement>("splitter");

let projectPath = "";
let mode: "review" | "auto" = "review";
let terminalRunning = false;
let taskSubmitting = false;
let unlistenTerminal: UnlistenFn | undefined;

const terminal = new Terminal({
  cursorBlink: true,
  convertEol: true,
  fontFamily:
    'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace',
  fontSize: 13,
  lineHeight: 1.35,
  scrollback: 4000,
  theme: {
    background: "#111417",
    foreground: "#d9e2ec",
    cursor: "#f4c430",
    selectionBackground: "#344150",
    black: "#111417",
    red: "#d95c5c",
    green: "#5dbb84",
    yellow: "#e2b84d",
    blue: "#6aa1e6",
    magenta: "#c678dd",
    cyan: "#5db7c7",
    white: "#d9e2ec",
    brightBlack: "#66717d",
    brightRed: "#ef7676",
    brightGreen: "#74d99f",
    brightYellow: "#f0cb67",
    brightBlue: "#86b7ff",
    brightMagenta: "#d998ec",
    brightCyan: "#78d8e5",
    brightWhite: "#f6f8fa",
  },
});
const fitAddon = new FitAddon();

terminal.loadAddon(fitAddon);
terminal.open(terminalHost);
terminal.onData((data) => {
  if (!terminalRunning) return;
  void invoke("terminal_write", { data }).catch((error) => {
    appendChat("system", `Terminal write failed: ${formatError(error)}`);
  });
});

void boot();

async function boot(): Promise<void> {
  installSplitter();
  installResizeObserver();

  try {
    unlistenTerminal = await listen<TerminalPayload>("terminal-output", (event) =>
      writeTerminalOutput(event.payload.data)
    );
  } catch {
    terminal.write("Native terminal bridge is available inside Tauri.\r\n");
  }

  const stored = localStorage.getItem("teak.projectPath");
  projectInput.value =
    stored || (await invoke<string>("default_project_path").catch(() => "."));
  appendChat(
    "teak",
    "Pick a project, then send a task. Review mode sends `teak plan` into the terminal so you can approve steps there."
  );
  await loadProject();
}

loadProjectButton.addEventListener("click", () => void loadProject());
restartTerminalButton.addEventListener("click", () => void restartTerminal());
statusButton.addEventListener("click", () => void sendTerminalCommand("teak status"));

reviewModeButton.addEventListener("click", () => setMode("review"));
autoModeButton.addEventListener("click", () => setMode("auto"));

chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  void submitTask();
});

window.addEventListener("beforeunload", () => {
  void unlistenTerminal?.();
  void invoke("terminal_stop").catch(() => undefined);
});

async function loadProject(): Promise<void> {
  const nextPath = projectInput.value.trim();
  if (!nextPath) {
    appendChat("system", "Enter a project path first.");
    return;
  }

  try {
    const snapshot = await invoke<ProjectSnapshot>("load_project", {
      projectPath: nextPath,
    });
    projectPath = snapshot.project_root;
    projectInput.value = projectPath;
    localStorage.setItem("teak.projectPath", projectPath);
    projectStatus.textContent = snapshot.brain_exists
      ? "Brain ready"
      : "Brain not initialized";
    const brandH1 = document.querySelector<HTMLHeadingElement>(".brand h1")!;

    appendChat("system", statusSummary(snapshot));
    await restartTerminal();
  } catch (error) {
    projectStatus.textContent = "Load failed";
    appendChat("system", `Project load failed: ${formatError(error)}`);
  }
}

async function restartTerminal(): Promise<void> {
  if (!projectPath) return;
  const size = fitTerminal();
  terminal.clear();
  terminalStatus.textContent = "Starting...";
  try {
    await invoke("terminal_start", {
      projectPath,
      cols: size.cols,
      rows: size.rows,
    });
    terminalRunning = true;
    terminalStatus.textContent = shortPath(projectPath);
    terminal.focus();
  } catch (error) {
    terminalRunning = false;
    terminalStatus.textContent = "Failed";
    appendChat("system", `Terminal failed to start: ${formatError(error)}`);
  }
}

async function sendTerminalCommand(command: string): Promise<void> {
  if (!terminalRunning) {
    await restartTerminal();
  }
  if (!terminalRunning) return;
  await invoke("terminal_write", { data: `${command}\r` }).catch((error) => {
    appendChat("system", `Could not send command: ${formatError(error)}`);
  });
  terminal.focus();
}

async function submitTask(): Promise<void> {
  if (taskSubmitting) return;
  const task = chatInput.value.trim();
  if (!task) return;

  taskSubmitting = true;
  sendButton.disabled = true;
  try {
    appendChat("user", task);
    chatInput.value = "";

    if (!(await ensureCleanWorkingTree())) {
      appendChat("teak", "Task not sent. Commit or stash the current changes, then send it again.");
      return;
    }

    const suffix = mode === "auto" ? " --auto" : "";
    const command = `teak plan ${shellQuote(task)}${suffix}`;
    appendChat(
      "teak",
      mode === "auto"
        ? "Running the task in auto mode in the terminal."
        : "Sent the task to the terminal. Use the terminal prompts for approve, edit, reject, and step review."
    );
    await sendTerminalCommand(command);
  } finally {
    taskSubmitting = false;
    sendButton.disabled = false;
  }
}

async function ensureCleanWorkingTree(): Promise<boolean> {
  if (!projectPath) {
    appendChat("system", "Load a project before sending a task.");
    return false;
  }

  try {
    const git = await invoke<GitSnapshot>("git_status", { projectPath });
    if (git.clean) {
      return true;
    }

    appendChat(
      "system",
      [
        "Teak cannot start a plan while the working tree has uncommitted changes.",
        "",
        git.output.trim(),
        "",
        ...dirtyTreeAdvice(git.output),
      ].join("\n")
    );
    await sendTerminalCommand("git status --short");
    return false;
  } catch (error) {
    appendChat(
      "system",
      `Could not check git status before running Teak: ${formatError(error)}`
    );
    return true;
  }
}

function setMode(nextMode: "review" | "auto"): void {
  mode = nextMode;
  reviewModeButton.classList.toggle("active", mode === "review");
  autoModeButton.classList.toggle("active", mode === "auto");
}

function dirtyTreeAdvice(status: string): string[] {
  const lines = status.split("\n");
  const hasTrackedTeakRuntime = lines.some((line) =>
    /^(?:[ MARCUD?!]{1,2})\s+\.teak\/(?:teak\.db|\.DS_Store)$/.test(line)
  );

  if (hasTrackedTeakRuntime) {
    return [
      "Teak runtime files are tracked in this repo. Untrack them once, then commit the cleanup:",
      "  printf \"teak.db\\n.DS_Store\\n\" > .teak/.gitignore",
      "  git rm --cached --ignore-unmatch .teak/teak.db .teak/.DS_Store",
      "  git add .teak/.gitignore",
      "  git commit -m \"Stop tracking Teak local state\"",
    ];
  }

  return [
    "Commit or stash these changes in the terminal, then send the task again:",
    "  git add . && git commit -m \"checkpoint\"",
    "  git stash push -u",
  ];
}

function appendChat(role: ChatRole, text: string): void {
  const message = document.createElement("article");
  message.className = `message ${role}`;

  const label = document.createElement("div");
  label.className = "message-label";
  label.textContent = role === "user" ? "You" : role === "teak" ? "Teak" : "System";

  const body = document.createElement("div");
  body.className = "message-body";
  body.textContent = text;

  message.append(label, body);
  chatMessages.append(message);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function statusSummary(snapshot: ProjectSnapshot): string {
  const files = snapshot.brain_files.filter((file) => file.content.trim()).length;
  const status = stripAnsi(snapshot.status).trim().split("\n").slice(0, 6).join("\n");
  return `Loaded ${shortPath(snapshot.project_root)}. Brain files: ${files}/4.\n${status}`;
}

function installSplitter(): void {
  let dragging = false;

  splitter.addEventListener("pointerdown", (event) => {
    dragging = true;
    splitter.setPointerCapture(event.pointerId);
    document.body.classList.add("resizing");
  });

  splitter.addEventListener("pointerup", (event) => {
    dragging = false;
    splitter.releasePointerCapture(event.pointerId);
    document.body.classList.remove("resizing");
  });

  splitter.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    const rect = root.getBoundingClientRect();
    const min = 320;
    const max = rect.width - min;
    const left = Math.min(max, Math.max(min, event.clientX - rect.left));
    root.style.setProperty("--left-pane", `${left}px`);
    resizeTerminal();
  });
}

function installResizeObserver(): void {
  const observer = new ResizeObserver(() => resizeTerminal());
  observer.observe(terminalHost);
  window.addEventListener("resize", resizeTerminal);
}

function resizeTerminal(): void {
  const size = fitTerminal();
  if (terminalRunning) {
    void invoke("terminal_resize", size).catch(() => undefined);
  }
}

function fitTerminal(): { cols: number; rows: number } {
  const wasAtBottom = terminalAtBottom();
  fitAddon.fit();
  if (wasAtBottom) {
    terminal.scrollToBottom();
  }
  return {
    cols: Math.max(30, terminal.cols),
    rows: Math.max(8, terminal.rows),
  };
}

function writeTerminalOutput(data: string): void {
  const shouldStickToBottom = terminalAtBottom();
  terminal.write(data, () => {
    if (shouldStickToBottom) {
      terminal.scrollToBottom();
    }
  });
}

function terminalAtBottom(): boolean {
  const buffer = terminal.buffer.active;
  return buffer.viewportY >= buffer.baseY - 1;
}

function shellQuote(value: string): string {
  return `'${value.replace(/'/g, `'\\''`)}'`;
}

function shortPath(path: string): string {
  const home = path.replace(new RegExp(`^/${"Users"}/[^/]+`), "~");
  const parts = home.split("/");
  if (parts.length <= 4) return home;
  return `${parts.slice(0, 2).join("/")}/.../${parts.slice(-2).join("/")}`;
}

function stripAnsi(value: string): string {
  return value.replace(/\u001b\[[0-9;]*m/g, "");
}

function formatError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function byId<T extends HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (!element) {
    throw new Error(`missing #${id}`);
  }
  return element as T;
}
