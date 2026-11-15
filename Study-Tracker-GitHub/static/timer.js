(() => {
  const root = document.getElementById("timer-app");
  if (!root) return;
  const clock = document.getElementById("timer-clock");
  const status = document.getElementById("timer-status");
  const error = document.getElementById("timer-error");
  const goal = document.getElementById("timer-goal");
  const form = document.getElementById("timer-save");
  const manualLink = document.getElementById("manual-session");
  const buttons = root.querySelectorAll("[data-timer]");
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  let state = JSON.parse(document.getElementById("timer-initial").textContent);
  let receivedAt = performance.now();
  let formToken = null;
  let busy = false;

  function renderClock() {
    let seconds = state ? state.elapsed : 0;
    if (state?.phase === "running") seconds += (performance.now() - receivedAt) / 1000;
    seconds = Math.max(0, Math.floor(seconds));
    clock.textContent = [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60]
      .map((part) => String(part).padStart(2, "0")).join(":");
  }

  function render() {
    const phase = state?.phase;
    status.textContent = { running: "Занятие идёт", paused: "На паузе", finished: "Завершено · сохрани результат" }[phase] || "Готов к занятию";
    goal.disabled = Boolean(state);
    if (state) goal.value = String(state.goal_id);
    if (manualLink) {
      manualLink.hidden = Boolean(state);
      manualLink.href = goal.selectedOptions[0].dataset.manualUrl;
    }
    const visible = {
      start: !state, pause: phase === "running", resume: phase === "paused",
      finish: phase === "running" || phase === "paused", cancel: Boolean(state),
    };
    buttons.forEach((button) => {
      button.hidden = !visible[button.dataset.timer];
      button.disabled = busy;
    });
    form.hidden = phase !== "finished";
    if (phase === "finished" && formToken !== state.token) {
      form.reset();
      form.elements.date.value = state.date;
      form.elements.duration_minutes.value = Math.max(1, Math.ceil(state.elapsed / 60));
      formToken = state.token;
    }
    form.querySelector("button").disabled = busy;
    renderClock();
  }

  async function request(action, payload = {}) {
    const response = await fetch("/api/timer/" + action, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: JSON.stringify(payload),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.error || "Не удалось выполнить действие. Обнови страницу и повтори.");
    return result;
  }

  async function sync() {
    if (busy) return;
    const previousState = state;
    try {
      const response = await fetch("/api/timer", { cache: "no-store" });
      if (!response.ok) throw new Error();
      const result = await response.json();
      // A later command owns the UI if it ran while this read was in flight.
      if (busy || state !== previousState) return;
      state = result.state;
      receivedAt = performance.now();
      if (error.textContent.startsWith("Связь")) error.textContent = "";
      render();
    } catch {
      error.textContent = "Связь с приложением прервалась. Таймер восстановится после подключения.";
    }
  }

  buttons.forEach((button) => button.addEventListener("click", async () => {
    if (busy) return;
    const action = button.dataset.timer;
    if (action === "cancel" && !window.confirm("Сбросить незаписанное занятие?")) return;
    busy = true;
    error.textContent = "";
    render();
    try {
      const result = await request(action, { goal_id: Number(goal.value), token: state?.token });
      state = result.state;
      receivedAt = performance.now();
    } catch (problem) {
      error.textContent = problem.message;
    } finally {
      busy = false;
      render();
    }
  }));

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy) return;
    busy = true;
    error.textContent = "";
    render();
    try {
      const data = Object.fromEntries(new FormData(form));
      await request("save", { ...data, token: formToken });
      state = null;
      formToken = null;
      form.reset();
      status.textContent = "Занятие сохранено";
      window.location.assign("/history?date=" + encodeURIComponent(data.date));
    } catch (problem) {
      error.textContent = problem.message;
    } finally {
      busy = false;
      render();
    }
  });
  goal.addEventListener("change", render);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) sync(); });
  window.addEventListener("pageshow", sync);
  setInterval(renderClock, 250);
  setInterval(sync, 3000);
  render();
})();
