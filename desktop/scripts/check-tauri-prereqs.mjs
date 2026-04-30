import { spawnSync } from "node:child_process";

const cargo = spawnSync("cargo", ["--version"], {
  encoding: "utf8",
  stdio: ["ignore", "pipe", "pipe"],
});

if (cargo.status === 0) {
  process.exit(0);
}

console.error(`
Teak Desktop needs Rust/Cargo before Tauri can start.

Install Rust, then open a new terminal and rerun:

  cd desktop
  npm run tauri

On macOS with Homebrew, the shortest install is:

  brew install rust

Official rustup install also works:

  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
  source "$HOME/.cargo/env"
`);

process.exit(1);
