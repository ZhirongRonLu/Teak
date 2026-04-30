use portable_pty::{native_pty_system, Child, CommandBuilder, MasterPty, PtySize};
use serde::Serialize;
use std::env;
use std::fs;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::Mutex;
use std::thread;
use tauri::{AppHandle, Emitter, State};

const BRAIN_FILES: [&str; 4] = [
    "ARCHITECTURE.md",
    "CONVENTIONS.md",
    "DECISIONS.md",
    "MEMORY.md",
];

struct TerminalSession {
    child: Box<dyn Child + Send>,
    writer: Box<dyn Write + Send>,
    master: Box<dyn MasterPty + Send>,
}

#[derive(Default)]
struct TerminalState {
    session: Mutex<Option<TerminalSession>>,
}

#[derive(Clone, Serialize)]
struct TerminalOutput {
    data: String,
}

#[derive(Serialize)]
struct BrainFile {
    name: String,
    path: String,
    content: String,
}

#[derive(Serialize)]
struct ProjectSnapshot {
    project_root: String,
    brain_exists: bool,
    brain_files: Vec<BrainFile>,
    status: String,
}

#[derive(Serialize)]
struct CommandOutput {
    code: i32,
    stdout: String,
    stderr: String,
}

#[tauri::command]
fn default_project_path() -> String {
    find_teak_source_root()
        .or_else(|| env::current_dir().ok())
        .map(|path| path.display().to_string())
        .unwrap_or_else(|| ".".to_string())
}

#[tauri::command]
fn load_project(project_path: String) -> Result<ProjectSnapshot, String> {
    let project_root = normalize_project_path(&project_path)?;
    let brain_dir = project_root.join(".teak").join("brain");
    let brain_exists = brain_dir.is_dir();
    let mut brain_files = Vec::new();

    for name in BRAIN_FILES {
        let path = brain_dir.join(name);
        let content = if path.is_file() {
            fs::read_to_string(&path).map_err(|e| format!("failed to read {name}: {e}"))?
        } else {
            String::new()
        };
        brain_files.push(BrainFile {
            name: name.to_string(),
            path: path.display().to_string(),
            content,
        });
    }

    let status = match run_teak_capture(&project_root, &["status"]) {
        Ok(output) if output.code == 0 => output.stdout,
        Ok(output) => {
            let text = format!("{}{}", output.stdout, output.stderr);
            if text.trim().is_empty() {
                format!("teak status exited with {}", output.code)
            } else {
                text
            }
        }
        Err(e) => format!("teak status unavailable: {e}"),
    };

    Ok(ProjectSnapshot {
        project_root: project_root.display().to_string(),
        brain_exists,
        brain_files,
        status,
    })
}

#[tauri::command]
fn save_brain_file(project_path: String, name: String, content: String) -> Result<(), String> {
    if !BRAIN_FILES.contains(&name.as_str()) {
        return Err(format!("not a Teak brain file: {name}"));
    }

    let project_root = normalize_project_path(&project_path)?;
    let brain_dir = project_root.join(".teak").join("brain");
    fs::create_dir_all(&brain_dir).map_err(|e| format!("failed to create brain dir: {e}"))?;
    fs::write(brain_dir.join(&name), content)
        .map_err(|e| format!("failed to write {name}: {e}"))?;
    Ok(())
}

#[tauri::command]
fn run_teak_status(project_path: String) -> Result<CommandOutput, String> {
    let project_root = normalize_project_path(&project_path)?;
    run_teak_capture(&project_root, &["status"])
}

#[tauri::command]
fn terminal_start(
    app: AppHandle,
    state: State<'_, TerminalState>,
    project_path: String,
    cols: u16,
    rows: u16,
) -> Result<(), String> {
    {
        let mut guard = state
            .session
            .lock()
            .map_err(|_| "terminal state poisoned".to_string())?;
        if let Some(mut session) = guard.take() {
            let _ = session.child.kill();
        }
    }

    let project_root = normalize_project_path(&project_path)?;
    let pty_system = native_pty_system();
    let pair = pty_system
        .openpty(PtySize {
            rows: rows.max(8),
            cols: cols.max(20),
            pixel_width: 0,
            pixel_height: 0,
        })
        .map_err(|e| format!("failed to open terminal: {e}"))?;

    let mut command = CommandBuilder::new(default_shell());
    command.cwd(&project_root);
    if let Some(source_root) = find_teak_source_root() {
        command.env("TEAK_SOURCE_ROOT", source_root.display().to_string());
        command.env("PYTHONPATH", python_path_with_source(&source_root));
        command.env("PATH", path_with_teak_venv(&source_root));
    }

    let child = pair
        .slave
        .spawn_command(command)
        .map_err(|e| format!("failed to start shell: {e}"))?;
    drop(pair.slave);

    let mut reader = pair
        .master
        .try_clone_reader()
        .map_err(|e| format!("failed to attach terminal reader: {e}"))?;
    let writer = pair
        .master
        .take_writer()
        .map_err(|e| format!("failed to attach terminal writer: {e}"))?;

    thread::spawn(move || {
        let mut buffer = [0_u8; 4096];
        loop {
            match reader.read(&mut buffer) {
                Ok(0) => break,
                Ok(n) => {
                    let data = String::from_utf8_lossy(&buffer[..n]).to_string();
                    let _ = app.emit("terminal-output", TerminalOutput { data });
                }
                Err(_) => break,
            }
        }
        let _ = app.emit(
            "terminal-output",
            TerminalOutput {
                data: "\r\n[terminal closed]\r\n".to_string(),
            },
        );
    });

    let mut guard = state
        .session
        .lock()
        .map_err(|_| "terminal state poisoned".to_string())?;
    *guard = Some(TerminalSession {
        child,
        writer,
        master: pair.master,
    });
    Ok(())
}

#[tauri::command]
fn terminal_write(state: State<'_, TerminalState>, data: String) -> Result<(), String> {
    let mut guard = state
        .session
        .lock()
        .map_err(|_| "terminal state poisoned".to_string())?;
    let session = guard
        .as_mut()
        .ok_or_else(|| "terminal is not running".to_string())?;
    session
        .writer
        .write_all(data.as_bytes())
        .map_err(|e| format!("terminal write failed: {e}"))?;
    session
        .writer
        .flush()
        .map_err(|e| format!("terminal flush failed: {e}"))?;
    Ok(())
}

#[tauri::command]
fn terminal_resize(state: State<'_, TerminalState>, cols: u16, rows: u16) -> Result<(), String> {
    let guard = state
        .session
        .lock()
        .map_err(|_| "terminal state poisoned".to_string())?;
    let session = guard
        .as_ref()
        .ok_or_else(|| "terminal is not running".to_string())?;
    session
        .master
        .resize(PtySize {
            rows: rows.max(8),
            cols: cols.max(20),
            pixel_width: 0,
            pixel_height: 0,
        })
        .map_err(|e| format!("terminal resize failed: {e}"))?;
    Ok(())
}

#[tauri::command]
fn terminal_stop(state: State<'_, TerminalState>) -> Result<(), String> {
    let mut guard = state
        .session
        .lock()
        .map_err(|_| "terminal state poisoned".to_string())?;
    if let Some(mut session) = guard.take() {
        let _ = session.child.kill();
    }
    Ok(())
}

fn normalize_project_path(project_path: &str) -> Result<PathBuf, String> {
    let expanded = expand_tilde(project_path);
    let path = PathBuf::from(expanded);
    let canonical = path
        .canonicalize()
        .map_err(|e| format!("project path is not readable: {e}"))?;
    if !canonical.is_dir() {
        return Err(format!("not a directory: {}", canonical.display()));
    }
    Ok(canonical)
}

fn expand_tilde(path: &str) -> String {
    if path == "~" {
        return env::var("HOME").unwrap_or_else(|_| path.to_string());
    }
    if let Some(rest) = path.strip_prefix("~/") {
        if let Ok(home) = env::var("HOME") {
            return format!("{home}/{rest}");
        }
    }
    path.to_string()
}

fn default_shell() -> String {
    if cfg!(windows) {
        env::var("COMSPEC").unwrap_or_else(|_| "cmd.exe".to_string())
    } else {
        env::var("SHELL").unwrap_or_else(|_| "/bin/zsh".to_string())
    }
}

fn find_teak_source_root() -> Option<PathBuf> {
    if let Ok(root) = env::var("TEAK_SOURCE_ROOT") {
        let path = PathBuf::from(root);
        if path.join("src").join("teak").is_dir() {
            return Some(path);
        }
    }

    let mut candidates = Vec::new();
    if let Ok(cwd) = env::current_dir() {
        candidates.push(cwd);
    }
    if let Ok(exe) = env::current_exe() {
        if let Some(parent) = exe.parent() {
            candidates.push(parent.to_path_buf());
        }
    }

    for start in candidates {
        for candidate in start.ancestors() {
            if candidate.join("pyproject.toml").is_file()
                && candidate.join("src").join("teak").is_dir()
            {
                return Some(candidate.to_path_buf());
            }
        }
    }
    None
}

fn python_path_with_source(source_root: &Path) -> String {
    let source = source_root.join("src").display().to_string();
    match env::var("PYTHONPATH") {
        Ok(existing) if !existing.trim().is_empty() => format!("{source}:{existing}"),
        _ => source,
    }
}

fn path_with_teak_venv(source_root: &Path) -> String {
    let bin_dir = if cfg!(windows) {
        source_root.join(".venv").join("Scripts")
    } else {
        source_root.join(".venv").join("bin")
    };
    let existing = env::var("PATH").unwrap_or_default();
    if bin_dir.is_dir() {
        let separator = if cfg!(windows) { ";" } else { ":" };
        if existing.trim().is_empty() {
            bin_dir.display().to_string()
        } else {
            format!("{}{}{}", bin_dir.display(), separator, existing)
        }
    } else {
        existing
    }
}

fn teak_python(source_root: &Path) -> PathBuf {
    let candidate = if cfg!(windows) {
        source_root.join(".venv").join("Scripts").join("python.exe")
    } else {
        source_root.join(".venv").join("bin").join("python")
    };
    if candidate.is_file() {
        candidate
    } else {
        PathBuf::from("python3")
    }
}

fn run_teak_capture(project_root: &Path, args: &[&str]) -> Result<CommandOutput, String> {
    let mut command = if let Some(source_root) = find_teak_source_root() {
        let mut command = Command::new(teak_python(&source_root));
        command.arg("-m").arg("teak");
        command.env("TEAK_SOURCE_ROOT", source_root.display().to_string());
        command.env("PYTHONPATH", python_path_with_source(&source_root));
        command.env("PATH", path_with_teak_venv(&source_root));
        command
    } else {
        Command::new("teak")
    };

    command.current_dir(project_root);
    for arg in args {
        command.arg(arg);
    }

    let output = command
        .output()
        .map_err(|e| format!("failed to run teak: {e}"))?;
    Ok(CommandOutput {
        code: output.status.code().unwrap_or(-1),
        stdout: String::from_utf8_lossy(&output.stdout).to_string(),
        stderr: String::from_utf8_lossy(&output.stderr).to_string(),
    })
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(TerminalState::default())
        .invoke_handler(tauri::generate_handler![
            default_project_path,
            load_project,
            save_brain_file,
            run_teak_status,
            terminal_start,
            terminal_write,
            terminal_resize,
            terminal_stop,
        ])
        .run(tauri::generate_context!())
        .expect("error while running Teak desktop");
}
