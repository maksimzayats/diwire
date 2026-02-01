(() => {
  let pyodideReady = null;
  let packagesInstalled = false;
  const NOT_EXECUTED_OUTPUT = "Not executed. Click Run to execute this example.";
  const NO_OUTPUT = "(no output)";

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

  function setOutputState(output, statusEl, state, message) {
    output.dataset.pyRunnerState = state;
    statusEl.textContent = message;
  }

  async function runCode(codeBlock, output, statusEl, outputPre, runButtons) {
    const pre = codeBlock.querySelector("pre");
    const code = pre ? pre.textContent ?? "" : codeBlock.textContent ?? "";

    for (const btn of runButtons) {
      btn.disabled = true;
      btn.innerHTML = spinnerSvg;
    }
    setOutputState(output, statusEl, "running", "Running...");
    outputPre.textContent = "Loading Python...";

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
import sys
import types

_stdout = StringIO()
_stderr = StringIO()
with redirect_stdout(_stdout), redirect_stderr(_stderr):
    # Execute in a real module so get_type_hints() can resolve names via sys.modules.
    _mod = types.ModuleType("__main__")
    _mod.__dict__["__name__"] = "__main__"
    _mod.__dict__["__package__"] = None

    _old_main = sys.modules.get("__main__")
    sys.modules["__main__"] = _mod
    try:
        exec(__RUN_CODE__, _mod.__dict__)
    finally:
        if _old_main is None:
            del sys.modules["__main__"]
        else:
            sys.modules["__main__"] = _old_main
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

      const combined = stdout + (stderr ? `\n${stderr}` : "");
      outputPre.textContent = combined.trim() ? combined : NO_OUTPUT;

      for (const btn of runButtons) {
        btn.disabled = false;
        showSuccess(btn, playSvg);
      }
      setOutputState(output, statusEl, "ok", "Executed");
    } catch (error) {
      outputPre.textContent = String(error);
      for (const btn of runButtons) {
        btn.disabled = false;
        btn.innerHTML = playSvg;
      }
      setOutputState(output, statusEl, "error", "Error");
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

    // Run buttons (play icon): show both on the code block and in the output panel.
    const runBtnMain = document.createElement("button");
    runBtnMain.type = "button";
    runBtnMain.className = "py-runner-btn py-runner-run o-tooltip--left";
    runBtnMain.setAttribute("data-tooltip", "Run");
    runBtnMain.innerHTML = playSvg;

    const runBtnOutput = document.createElement("button");
    runBtnOutput.type = "button";
    runBtnOutput.className = "py-runner-btn py-runner-run o-tooltip--left";
    runBtnOutput.setAttribute("data-tooltip", "Run");
    runBtnOutput.innerHTML = playSvg;

    // Edit button (pencil icon)
    const editBtn = document.createElement("button");
    editBtn.type = "button";
    editBtn.className = "py-runner-btn py-runner-edit o-tooltip--left";
    editBtn.setAttribute("data-tooltip", "Edit");
    editBtn.innerHTML = pencilSvg;

    const output = document.createElement("div");
    output.className = "py-runner-output";
    output.dataset.pyRunnerState = "idle";

    const toolbar = document.createElement("div");
    toolbar.className = "py-runner-output-toolbar";

    const label = document.createElement("div");
    label.className = "py-runner-output-label";

    const title = document.createElement("span");
    title.className = "py-runner-output-title";
    title.textContent = "Output";

    const status = document.createElement("span");
    status.className = "py-runner-output-status";
    status.textContent = "Not executed";

    label.appendChild(title);
    label.appendChild(status);

    const actions = document.createElement("div");
    actions.className = "py-runner-output-actions";
    actions.appendChild(runBtnOutput);

    toolbar.appendChild(label);
    toolbar.appendChild(actions);

    const outputPre = document.createElement("pre");
    outputPre.className = "py-runner-output-pre";
    outputPre.textContent = NOT_EXECUTED_OUTPUT;
    outputPre.setAttribute("aria-live", "polite");

    output.appendChild(toolbar);
    output.appendChild(outputPre);

    // Keep the Edit button attached to the code block itself.
    // The output panel should only show Run.
    const highlight = codeBlock.querySelector(".highlight") || codeBlock;
    highlight.appendChild(editBtn);
    highlight.appendChild(runBtnMain);

    codeBlock.insertAdjacentElement("afterend", output);

    if (pre) {
      editBtn.addEventListener("click", () => toggleEditing(pre, editBtn));
    }
    const runButtons = [runBtnMain, runBtnOutput];
    runBtnMain.addEventListener("click", () => runCode(codeBlock, output, status, outputPre, runButtons));
    runBtnOutput.addEventListener("click", () => runCode(codeBlock, output, status, outputPre, runButtons));
  }

  document.addEventListener("DOMContentLoaded", () => {
    const config = window.PYODIDE_RUNNER_CONFIG || {};
    const selector = config.selector || ".py-run";
    document.querySelectorAll(selector).forEach(decorate);
  });
})();
