// The story pages' script: the landing page's tabs, a minute of video each (data-tabs-for), and Getting
// started as a stepper (data-stepper). Without script every film and every step shows, one after another.
// Plain script, no dependencies.
(() => {
  "use strict";

  const reduced = matchMedia("(prefers-reduced-motion: reduce)");

  // Tabs over panels: a tab shows its panel and hides the rest, pausing a film it hides. The page's
  // address can name a panel (/#evaluation); else the tab the page marks selected opens.
  function tabs(group) {
    const buttons = [...group.querySelectorAll("[data-tab]")];
    const panels = [...document.querySelectorAll(`[data-panel-for="${group.dataset.tabsFor}"]`)];
    const choose = (name, focus) => {
      for (const button of buttons) {
        const chosen = button.dataset.tab === name;
        button.setAttribute("aria-selected", String(chosen));
        button.tabIndex = chosen ? 0 : -1;
        if (chosen && focus) button.focus();
      }
      for (const panel of panels) {
        panel.hidden = panel.dataset.panel !== name;
        if (panel.hidden) for (const video of panel.querySelectorAll("video")) video.pause();
      }
    };
    group.addEventListener("click", event => {
      const button = event.target.closest("[data-tab]");
      if (button) choose(button.dataset.tab, false);
    });
    group.addEventListener("keydown", event => {
      const index = buttons.findIndex(button => button.getAttribute("aria-selected") === "true");
      const move = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
      if (!move) return;
      event.preventDefault();
      choose(buttons[(index + move + buttons.length) % buttons.length].dataset.tab, true);
    });
    const named = buttons.find(button => `#${button.dataset.tab}` === location.hash);
    const marked = buttons.find(button => button.getAttribute("aria-selected") === "true");
    choose((named ?? marked ?? buttons[0]).dataset.tab, false);
  }

  // Getting started as a stepper: one step at a time, its number pills above.
  function stepper(root) {
    const steps = [...root.querySelectorAll(".step")];
    const rail = document.querySelector(`[data-stepper-rail="${root.id}"]`);
    if (!rail || !steps.length) return;
    rail.innerHTML = steps.map((step, index) =>
      `<button type="button" role="tab" data-go="${index}" aria-controls="${step.id}" aria-label="${step.querySelector("h2").textContent}"><span>${index + 1}</span><em>${step.querySelector("h2").textContent}</em></button>`).join("");
    const card = root.parentElement;
    const pager = card.querySelector("[data-stepper-pager]");
    let current = 0;
    let turn = 0;
    const mark = index => {
      for (const button of rail.querySelectorAll("[data-go]")) {
        const at = Number(button.dataset.go);
        button.setAttribute("aria-selected", String(at === index));
        button.tabIndex = at === index ? 0 : -1;
        button.classList.toggle("done", at < index);
      }
      // The rail scrolled to the chosen step, the steps after it in view and a little of the one before.
      const chosen = rail.querySelector(`[data-go="${index}"]`).getBoundingClientRect();
      const left = rail.scrollLeft + chosen.left - rail.getBoundingClientRect().left - 48;
      rail.scrollTo({ left: Math.max(0, left), behavior: reduced.matches ? "auto" : "smooth" });
      if (pager) {
        pager.querySelector("[data-step-back]").disabled = index === 0;
        pager.querySelector("[data-step-next]").disabled = index === steps.length - 1;
        pager.querySelector(".where").textContent = `${index + 1} of ${steps.length}`;
        pager.dataset.at = String(index);
      }
    };
    // The step and what follows it in view, with room below: the card's foot if it fits the window,
    // else its top.
    const reveal = () => {
      const box = card.getBoundingClientRect();
      const buffer = 48;
      const fits = box.height + buffer + 16 <= innerHeight;
      const by = !fits || box.top < 16 ? box.top - 16 : Math.max(0, box.bottom + buffer - innerHeight);
      if (Math.abs(by) > 1) scrollBy({ top: by, behavior: reduced.matches ? "auto" : "smooth" });
    };
    const phase = (element, keyframes, duration) =>
      element.animate(keyframes, { duration, easing: "ease-out", fill: "forwards" }).finished;
    // Fades the old step out, eases the list to the new one's height, fades the new one in; with
    // reduced motion, the new step at once. A later choice cuts a running one short.
    const go = async (index, scroll) => {
      if (index === current) return;
      const from = steps[current];
      const to = steps[index];
      current = index;
      const mine = ++turn;
      mark(index);
      for (const step of steps) for (const animation of step.getAnimations()) animation.cancel();
      for (const animation of root.getAnimations()) animation.cancel();
      if (reduced.matches) {
        steps.forEach((step, at) => { step.hidden = at !== index; });
        if (scroll) reveal();
        return;
      }
      try {
        await phase(from, [{ opacity: 1 }, { opacity: 0 }], 140);
        if (mine !== turn) return;
        const before = root.offsetHeight;
        steps.forEach((step, at) => { step.hidden = at !== index; });
        to.style.opacity = "0";
        const after = root.offsetHeight;
        await phase(root, [{ height: `${before}px` }, { height: `${after}px` }], 160);
        if (mine !== turn) return;
        for (const animation of root.getAnimations()) animation.cancel();
        if (scroll) reveal();
        await phase(to, [{ opacity: 0 }, { opacity: 1 }], 150);
      } catch {
        // Cancelled by a later choice, which draws its own step.
      } finally {
        if (mine === turn) {
          steps.forEach((step, at) => { step.hidden = at !== index; step.style.opacity = ""; });
          for (const step of steps) for (const animation of step.getAnimations()) animation.cancel();
        }
      }
    };
    rail.addEventListener("click", event => {
      const button = event.target.closest("[data-go]");
      if (button) go(Number(button.dataset.go), true);
    });
    rail.addEventListener("keydown", event => {
      const move = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
      if (!move) return;
      event.preventDefault();
      const index = Math.min(steps.length - 1, Math.max(0, current + move));
      go(index, true);
      rail.querySelector(`[data-go="${index}"]`).focus();
    });
    pager?.addEventListener("click", event => {
      if (event.target.closest("[data-step-back]")) go(Math.max(0, current - 1), true);
      if (event.target.closest("[data-step-next]")) go(Math.min(steps.length - 1, current + 1), true);
    });
    root.classList.add("stepping");
    steps.forEach((step, at) => { step.hidden = at !== 0; });
    mark(0);
  }

  function start() {
    for (const group of document.querySelectorAll("[data-tabs-for]")) tabs(group);
    for (const root of document.querySelectorAll("[data-stepper]")) stepper(root);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
