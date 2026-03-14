import { spawn } from "node:child_process";
import process from "node:process";

const python = process.env.PYTHON_BIN || "python";
const child = spawn(python, ["-u", "run_wsgi_server.py"], {
  cwd: process.cwd(),
  stdio: "inherit",
});

const forwardSignal = (signal) => {
  if (!child.killed) {
    child.kill(signal);
  }
};

process.on("SIGINT", () => forwardSignal("SIGINT"));
process.on("SIGTERM", () => forwardSignal("SIGTERM"));

child.on("exit", (code) => {
  process.exit(code ?? 0);
});
