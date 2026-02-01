(() => {
  let pyodideReady = null;
  let packagesInstalled = false;

  async function loadPyodideOnce() {
    if (!pyodideReady) {
      pyodideReady = loadPyodide();
    }
    return pyodideReady;
  }

  async function installPackages(pyodide) {
    if (packagesInstalled) {
      return;
    }
    const config = window.PYODIDE_RUNNER_CONFIG || {};
    const packages = Array.isArray(config.packages) ? config.packages : [];
    if (packages.length === 0) {
      packagesInstalled = true;
      return;
    }
    await pyodide.loadPackage("micropip");
    const escaped = packages.map((p) => `"${p}"`).join(", ");
    await pyodide.runPythonAsync(`
import micropip
await micropip.install([${escaped}])
`);
    packagesInstalled = true;
  }

  // SVG icons
  const playSvg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>`;
  const pencilSvg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg>`;
  const spinnerSvg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="16" height="16" fill="currentColor" class="pyodide-spinner"><path d="M12 2a10 10 0 0 1 10 10h-2a8 8 0 0 0-8-8V2z"/></svg>`;

  function enableEditing(pre) {
    if (!pre || pre.dataset.pyRunnerEditable === "1") {
      return;
    }

    pre.dataset.pyRunnerEditable = "1";
    pre.dataset.pyRunnerOriginalHtml = pre.innerHTML;
    pre.dataset.pyRunnerOriginalText = pre.textContent ?? "";

    // Keep syntax highlighting spans intact — browsers handle
    // contenteditable with inline spans well enough for small edits.
    pre.setAttribute("contenteditable", "true");
    pre.setAttribute("spellcheck", "false");
    pre.classList.add("py-runner-editable");
  }

  function disableEditing(pre, editBtn) {
    if (!pre || pre.dataset.pyRunnerEditable !== "1") {
      return;
    }

    const currentText = pre.textContent ?? "";
    const originalText = pre.dataset.pyRunnerOriginalText ?? "";

    pre.dataset.pyRunnerEditable = "0";
    pre.removeAttribute("contenteditable");
    pre.classList.remove("py-runner-editable");
    editBtn.classList.remove("active");

    // Restore original highlighted HTML if the text was not modified.
    // If the user edited the code, the spans may be mangled — leave as-is.
    if (currentText === originalText && pre.dataset.pyRunnerOriginalHtml) {
      pre.innerHTML = pre.dataset.pyRunnerOriginalHtml;
    }
  }

  function toggleEditing(pre, editBtn) {
    if (pre.dataset.pyRunnerEditable === "1") {
      disableEditing(pre, editBtn);
    } else {
      enableEditing(pre);
      editBtn.classList.add("active");
    }
  }

  async function runCode(codeBlock, output, outputPre, runBtn) {
    const pre = codeBlock.querySelector("pre");
    const code = pre ? pre.textContent ?? "" : codeBlock.textContent ?? "";

    runBtn.disabled = true;
    const prevHtml = runBtn.innerHTML;
    runBtn.innerHTML = spinnerSvg;
    output.classList.add("is-visible");
    outputPre.textContent = "Loading Pyodide...";

    let pyodide = null;

    try {
      pyodide = await loadPyodideOnce();
      await installPackages(pyodide);

      if (typeof pyodide.loadPackagesFromImports === "function") {
        await pyodide.loadPackagesFromImports(code);
      }

      pyodide.globals.set("__RUN_CODE__", code);
      const result = await pyodide.runPythonAsync(`
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO

_stdout = StringIO()
_stderr = StringIO()
with redirect_stdout(_stdout), redirect_stderr(_stderr):
    exec(__RUN_CODE__, {})
(_stdout.getvalue(), _stderr.getvalue())
`);

      let stdout = "";
      let stderr = "";

      if (result && typeof result.toJs === "function") {
        const data = result.toJs();
        result.destroy();
        stdout = data[0] ?? "";
        stderr = data[1] ?? "";
      } else if (Array.isArray(result)) {
        stdout = result[0] ?? "";
        stderr = result[1] ?? "";
      } else if (result !== null && result !== undefined) {
        stdout = String(result);
      }

      outputPre.textContent = stdout + (stderr ? `\n${stderr}` : "");
    } catch (error) {
      outputPre.textContent = String(error);
    } finally {
      if (pyodide) {
        try {
          pyodide.globals.delete("__RUN_CODE__");
        } catch {
          // Best effort cleanup.
        }
      }
      runBtn.disabled = false;
      runBtn.innerHTML = prevHtml;
    }
  }

  function decorate(codeBlock) {
    if (codeBlock.dataset.pyRunner === "1") {
      return;
    }
    codeBlock.dataset.pyRunner = "1";

    const pre = codeBlock.querySelector("pre");

    // Run button (play icon)
    const runBtn = document.createElement("button");
    runBtn.type = "button";
    runBtn.className = "py-runner-btn py-runner-run";
    runBtn.title = "Run code";
    runBtn.innerHTML = playSvg;

    // Edit button (pencil icon)
    const editBtn = document.createElement("button");
    editBtn.type = "button";
    editBtn.className = "py-runner-btn py-runner-edit";
    editBtn.title = "Toggle editing";
    editBtn.innerHTML = pencilSvg;

    const output = document.createElement("div");
    output.className = "highlight py-runner-output";
    const outputPre = document.createElement("pre");
    output.appendChild(outputPre);

    codeBlock.appendChild(editBtn);
    codeBlock.appendChild(runBtn);
    codeBlock.insertAdjacentElement("afterend", output);

    if (pre) {
      editBtn.addEventListener("click", () => toggleEditing(pre, editBtn));
    }
    runBtn.addEventListener("click", () => runCode(codeBlock, output, outputPre, runBtn));
  }

  document.addEventListener("DOMContentLoaded", () => {
    const config = window.PYODIDE_RUNNER_CONFIG || {};
    const selector = config.selector || ".py-run";
    document.querySelectorAll(selector).forEach(decorate);
  });
})();
