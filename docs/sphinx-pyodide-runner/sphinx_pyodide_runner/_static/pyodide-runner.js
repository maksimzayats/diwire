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

  // Tabler icons — same SVG structure as sphinx-copybutton's icon
  const playSvg = `<svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-player-play" width="44" height="44" viewBox="0 0 24 24" stroke-width="1.5" stroke="#000000" fill="none" stroke-linecap="round" stroke-linejoin="round"><path stroke="none" d="M0 0h24v24H0z" fill="none"/><path d="M7 4v16l13-8z"/></svg>`;
  const pencilSvg = `<svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-edit" width="44" height="44" viewBox="0 0 24 24" stroke-width="1.5" stroke="#000000" fill="none" stroke-linecap="round" stroke-linejoin="round"><path stroke="none" d="M0 0h24v24H0z" fill="none"/><path d="M7 7h-1a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2v-1"/><path d="M20.385 6.585a2.1 2.1 0 0 0-2.97-2.97l-8.415 8.385v3h3l8.385-8.415z"/></svg>`;
  const checkSvg = `<svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-check" width="44" height="44" viewBox="0 0 24 24" stroke-width="1.5" stroke="#000000" fill="none" stroke-linecap="round" stroke-linejoin="round"><path stroke="none" d="M0 0h24v24H0z" fill="none"/><path d="M5 12l5 5l10-10"/></svg>`;
  const spinnerSvg = `<svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-loader-2 pyodide-spinner" width="44" height="44" viewBox="0 0 24 24" stroke-width="1.5" stroke="#000000" fill="none" stroke-linecap="round" stroke-linejoin="round"><path stroke="none" d="M0 0h24v24H0z" fill="none"/><path d="M12 3a9 9 0 1 0 9 9"/></svg>`;

  function showSuccess(btn, originalSvg) {
    btn.innerHTML = checkSvg;
    btn.classList.add("success");
    setTimeout(() => {
      btn.innerHTML = originalSvg;
      btn.classList.remove("success");
    }, 2000);
  }

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

      runBtn.disabled = false;
      showSuccess(runBtn, playSvg);
    } catch (error) {
      outputPre.textContent = String(error);
      runBtn.disabled = false;
      runBtn.innerHTML = playSvg;
    } finally {
      if (pyodide) {
        try {
          pyodide.globals.delete("__RUN_CODE__");
        } catch {
          // Best effort cleanup.
        }
      }
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
    runBtn.className = "py-runner-btn py-runner-run o-tooltip--left";
    runBtn.setAttribute("data-tooltip", "Run");
    runBtn.innerHTML = playSvg;

    // Edit button (pencil icon)
    const editBtn = document.createElement("button");
    editBtn.type = "button";
    editBtn.className = "py-runner-btn py-runner-edit o-tooltip--left";
    editBtn.setAttribute("data-tooltip", "Edit");
    editBtn.innerHTML = pencilSvg;

    const output = document.createElement("div");
    output.className = "highlight py-runner-output";
    const outputPre = document.createElement("pre");
    output.appendChild(outputPre);

    // Place buttons inside .highlight (same container as copybutton)
    const highlight = codeBlock.querySelector(".highlight") || codeBlock;
    highlight.appendChild(editBtn);
    highlight.appendChild(runBtn);
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
