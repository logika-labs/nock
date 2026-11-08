// nock.dev's demo, coded rather than recorded so it stays current: three scenes in the studio's own
// visual language (the Work scene in its very classes, with its stylesheet), each a short script of
// steps with a caption line, played, paused, stepped and replayed. Every element of a scene says from
// which step it shows (data-at) and until which (data-until), and which classes it takes from which
// step (data-on="1:open 3:accepted"), so any step is drawn the same whichever way it is reached.
// The layouts place it: a stage per scene (data-demo="review"), one stage with tabs (data-tabs), or
// one stage the copy's beats drive as they scroll by (data-driven). With reduced motion nothing
// plays by itself: the steps are there to step through. Plain script, no dependencies.
(() => {
  "use strict";

  const ICON = {
    play: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M5 3.5v9l7-4.5z" fill="currentColor"/></svg>',
    pause: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 3.5h2.5v9H4.5zM9 3.5h2.5v9H9z" fill="currentColor"/></svg>',
    replay: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 8a4.5 4.5 0 1 0 1.4-3.3M3.5 2.5v2.6h2.6" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    back: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M10 3.5 5.5 8l4.5 4.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    next: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m6 3.5 4.5 4.5L6 12.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    chat: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 4.5h12a1.5 1.5 0 0 1 1.5 1.5v7a1.5 1.5 0 0 1-1.5 1.5H9l-3.5 3v-3H4A1.5 1.5 0 0 1 2.5 13V6A1.5 1.5 0 0 1 4 4.5z" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>',
    caret: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m6 4 4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    accepted: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m3.5 8.5 3 3 6-7" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    rejected: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4.5 4.5 7 7m0-7-7 7" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>',
    out: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3.5h6.5V10M12.5 3.5 4 12" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  };
  const mark = (verdict, at, until) => `<span class="verdict-mark ${verdict}" role="img" aria-label="${verdict === "accepted" ? "Accepted" : "Rejected"}" data-at="${at}"${until === undefined ? "" : ` data-until="${until}"`}>${ICON[verdict]}</span>`;
  const call = (tool, command, end = "", delay = 0, extra = "") =>
    `<li class="call${end ? ` ${end}` : ""}" style="--d:${delay}s" ${extra}><span class="tool">${tool}</span><code>${command}</code>${end === "failed" ? '<span class="exit">exit 1</span>' : end === "ok" ? '<span class="exit">exit 0</span>' : ""}</li>`;

  // An email, as the screenshots an agent submits: the first take loud, the second calm.
  const email = (loud) => {
    const svg = `<svg xmlns='http://www.w3.org/2000/svg' width='240' height='300' viewBox='0 0 240 300'>
      <rect width='240' height='300' fill='#f6f4fb'/>
      <rect x='16' y='16' width='208' height='268' rx='10' fill='#fff' stroke='#e4e0ef'/>
      ${loud ? "<rect x='16' y='16' width='208' height='46' rx='10' fill='#e0243f'/><rect x='16' y='50' width='208' height='12' fill='#e0243f'/><text x='120' y='45' font-family='Arial' font-weight='700' font-size='15' fill='#fff' text-anchor='middle'>PAYMENT FAILED!</text>"
        : "<circle cx='40' cy='42' r='10' fill='#111116'/><rect x='58' y='37' width='70' height='10' rx='5' fill='#d9d5e6'/>"}
      <text x='32' y='${loud ? 96 : 90}' font-family='Arial' font-weight='700' font-size='${loud ? 15 : 14}' fill='#111116'>${loud ? "Act now or lose access" : "Your card was declined"}</text>
      <rect x='32' y='110' width='176' height='8' rx='4' fill='#e7e3f1'/><rect x='32' y='126' width='150' height='8' rx='4' fill='#e7e3f1'/><rect x='32' y='142' width='164' height='8' rx='4' fill='#e7e3f1'/>
      <rect x='32' y='170' width='${loud ? 176 : 120}' height='34' rx='${loud ? 4 : 17}' fill='${loud ? "#e0243f" : "#111116"}'/>
      <text x='${loud ? 120 : 92}' y='192' font-family='Arial' font-weight='700' font-size='12' fill='#fff' text-anchor='middle'>${loud ? "PAY IMMEDIATELY" : "Update your card"}</text>
      <rect x='32' y='228' width='120' height='7' rx='3.5' fill='#efecf6'/><rect x='32' y='242' width='90' height='7' rx='3.5' fill='#efecf6'/>
    </svg>`;
    return "data:image/svg+xml," + encodeURIComponent(svg.replace(/\s+/g, " "));
  };

  const SCENES = {
    reflection: {
      label: "Reflection",
      steps: [
        { caption: "Your agent works, and every tool call is recorded on your machine.", hold: 4200 },
        { caption: "A failure repeats: the next session runs the same five commands to learn why a test fails.", hold: 4600 },
        { caption: "A reflection round reads the telemetry and writes the tool that was missing.", hold: 5200 },
        { caption: "The next session uses it: one call, and the answer.", hold: 4600 },
      ],
      markup: () => `<div class="scene-reflection">
        <div class="session terminal-card">
          <div class="bar"><span class="who" data-until="1">claude · session 14</span><span class="who" data-at="1" data-until="3">claude · session 15</span><span class="who" data-at="3">claude · session 17</span><span class="tag">recorded</span></div>
          <ol class="calls">
            ${call("Bash", "pytest -q tests/unit", "failed", 0, 'data-until="3"')}
            ${call("Bash", "pytest -q tests/unit 2&gt;&amp;1 | tail -30", "failed", 0.6, 'data-until="3"')}
            ${call("Read", "tests/unit/test_cart.py", "", 1.2, 'data-until="3"')}
            ${call("Bash", "pytest -q -k total -vv | grep -A5 Error", "failed", 1.8, 'data-until="3"')}
            ${call("Edit", "src/cart.py", "", 2.4, 'data-until="1"')}
            <li class="divider" data-at="1" data-until="3">the next day</li>
            ${call("Bash", "pytest -q tests/unit", "failed again", 0.4, 'data-at="1" data-until="3"')}
            ${call("Bash", "pytest -q tests/unit 2&gt;&amp;1 | tail -30", "failed again", 1, 'data-at="1" data-until="3"')}
            ${call("Bash", "pytest -q -k empty -vv | grep -A5 Error", "failed again", 1.6, 'data-at="1" data-until="3"')}
            <li class="divider" data-at="3">after the round</li>
            ${call("Bash", ".nock/nock failures --path tests/unit", "", 0.2, 'data-at="3"')}
            <li class="output" data-at="3" style="--d:.8s"><pre>test,error
tests/unit/test_cart.py::test_total,assert 41 == 42
tests/unit/test_cart.py::test_empty,KeyError: 'items'</pre></li>
            <li class="saved" data-at="3" style="--d:1.4s"><span class="chip-foil">1 call where there were 5</span></li>
          </ol>
        </div>
        <div class="side">
          <div class="sheet record" data-until="2">
            <span class="label">.nock/local/nock.db</span>
            <dl class="numbers">
              <div><dt>sessions</dt><dd><span data-until="1">14</span><span data-at="1">15</span></dd></div>
              <div><dt>tool calls</dt><dd><span data-until="1">1,180</span><span data-at="1">1,204</span></dd></div>
              <div><dt>failed</dt><dd><span data-until="1">88</span><span data-at="1">96</span></dd></div>
            </dl>
            <p class="pattern" data-at="1" style="--d:1.8s"><strong>recurs:</strong> <code>pytest … | tail</code>, <code>grep -A5 Error</code>: 23 times in 9 sessions</p>
          </div>
          <div class="sheet round" data-at="2">
            <div class="round-head"><span class="state-mark active" role="img" aria-label="Under way" data-until="3"></span><span class="state-mark done" role="img" aria-label="Done" data-at="3">${ICON.accepted}</span><strong>Reflection round</strong><time>8 Nov</time></div>
            <p class="reading" style="--d:.3s">The toolbox part reads 15 sessions, each tool's calls and failures, and the shell work that recurs.</p>
            <div class="writes" style="--d:1s"><span class="label">writes .nock/tools/tests.py</span>
<pre class="code"><code><span class="t-meta">@nock.command</span>(cache=<span class="t-string">"src/** tests/**"</span>)
<span class="t-keyword">def</span> <span class="t-call">failures</span>(sh, *, path: <span class="t-type">str</span> = <span class="t-string">"tests"</span>) -&gt; <span class="t-type">list</span>[<span class="t-type">dict</span>]:
    <span class="t-string">"""The failing tests, with the first line of each error."""</span>
    run = <span class="t-call">sh</span>(<span class="t-string">f"python -m pytest -q -rf {path}"</span>, check=<span class="t-keyword">False</span>)
    <span class="t-keyword">return</span> [{<span class="t-string">"test"</span>: t, <span class="t-string">"error"</span>: e} <span class="t-keyword">for</span> t, e <span class="t-keyword">in</span> <span class="t-call">parse</span>(run.lines)]</code></pre></div>
            <p class="expects" style="--d:1.8s"><strong>expects</strong> by the next round: one call where five were.</p>
          </div>
        </div>
      </div>`,
    },
    review: {
      label: "Review",
      steps: [
        { caption: "An agent opens a topic in Work: a decision, an image and a text.", hold: 4200 },
        { caption: "You open the decision: the answer, and what was considered instead.", hold: 4400 },
        { caption: "You ask about it in its chat, and the agent answers.", hold: 4800 },
        { caption: "You accept it.", hold: 3200 },
        { caption: "The email shouts: you reject the image.", hold: 3600 },
        { caption: "Version 2 arrives, and waits for your look.", hold: 4200 },
      ],
      markup: () => `<div class="topics scene-review">
        <div class="controls"><div class="bar"><div class="field"><input type="search" placeholder="Search the topics" aria-label="Search the topics" tabindex="-1" readonly></div>
          <div class="modes" role="group" aria-label="Search or ask"><button type="button" aria-pressed="true" tabindex="-1">Search</button><button type="button" aria-pressed="false" tabindex="-1">Ask</button></div></div></div>
        <article class="sheet topic open" data-at="0">
          <div class="main">
            <div class="topic-head">
              <span class="title-line"><span class="name">charge-sweep</span><span class="status">requeueing dead charges</span></span>
              <span class="corner"><span class="state-mark active" role="img" aria-label="Active"></span><time data-until="5">2m</time><time data-at="5">now</time><span class="chat-anchor"><span class="chat-toggle">${ICON.chat}</span></span></span>
              <span class="counts"><span>1 decision · 1 image · 1 text</span><span data-until="3">3 open</span><span data-at="3" data-until="4">2 open · 1 accepted</span><span data-at="4" data-until="5">1 open · 1 accepted · 1 rejected</span><span data-at="5">2 open · 1 accepted</span></span>
              <p class="about">The nightly sweep of failed charges, for the payments rework.</p>
            </div>
            <div class="topic-body">
              <section class="section decision" style="--d:.3s" data-at="0"><h3 class="label"><span class="fold">${ICON.caret}Decisions <span class="count">· 1</span></span></h3>
                <div class="item-bubbles"><div class="item-bubble decision" data-on="1:open 3:closed">
                  <div class="head"><span class="title">The sweep requeues dead charges only</span>
                    <span class="corner">${mark("accepted", 3)}<time>2m</time><span class="chat-anchor" data-on="2:open 3:shut"><span class="chat-toggle" data-on="2:pressed 3:unpressed">${ICON.chat}</span>
                      <aside class="chat" aria-label="Chat" data-at="2" data-until="3"><div class="chat-head"><span class="label">Chat</span></div>
                        <div class="messages"><div class="message owner" style="--d:.2s"><div class="context"><p>Why not requeue the failed ones too?</p></div><span class="when">just now</span></div>
                          <div class="message agent" style="--d:1.8s"><div class="context"><p>They're on their backoff already: requeueing them doubles the attempts. Dead jobs have nobody retrying them.</p></div><span class="when">just now</span></div></div>
                      </aside></span></span></div>
                  <div class="expanded" data-at="1" data-until="3"><div class="context"><p>The nightly sweep picks up charges whose job died, not ones still retrying.</p></div>
                    <div class="considered"><span class="label">Considered instead</span><ul class="alternatives"><li><span class="option">Requeue failed and dead jobs</span> — <span class="why">failed jobs are on their backoff; it doubles the attempts</span></li></ul></div>
                    <div class="actions"><span class="hint"></span><div class="buttons"><span class="button secondary">Drop</span><span class="button secondary">Reject</span><span class="button primary" data-on="2:pressing">Accept</span></div></div></div>
                </div></div></section>
              <section class="section image" style="--d:.7s" data-at="0"><h3 class="label"><span class="fold">${ICON.caret}Images <span class="count">· 1</span></span></h3>
                <div class="strip images"><span class="thumb" data-on="4:judged">
                  <img src="${email(true)}" alt="The lapsed payment email, first take" data-until="5"><img src="${email(false)}" alt="The lapsed payment email, version 2" data-at="5">
                  <span class="ribbon"><span class="title">The lapsed payment email</span><time data-until="5">1m</time><time data-at="5">now</time>${mark("rejected", 4, 5)}</span>
                  <span class="version-pill" data-at="5">Version 2</span></span></div></section>
              <section class="section text" style="--d:1.1s" data-at="0"><h3 class="label"><span class="fold">${ICON.caret}Texts <span class="count">· 1</span></span></h3>
                <div class="strip texts"><span class="preview"><span class="head"><span class="title">The lapsed email's copy</span><span class="side"><time>1m</time></span></span>
                  <pre>Subject: Your card was declined

We couldn't take this month's payment.
Update your card and we'll try again
tonight; nothing changes until then.</pre></span></div></section>
            </div>
          </div>
        </article>
      </div>`,
    },
    logika: {
      label: "Logika",
      steps: [
        { caption: "A change lands: webhooks retry when a delivery fails.", hold: 4200 },
        { caption: "The logika round reads the evidence map and gives the retry risk its rule.", hold: 5000 },
        { caption: "Production breaks it: a delivery that failed for good is retried.", hold: 4200 },
        { caption: "Within five minutes an issue, with its evidence, wakes your agent.", hold: 4600 },
        { caption: "The fix lands the way your repository delivers anything, and the report joins the thread.", hold: 5200 },
      ],
      markup: () => `<div class="scene-logika">
        <div class="left">
          <div class="terminal-card code-card" data-until="3">
            <div class="bar"><span class="who">src/webhooks/deliver.py</span><span class="tag">the change</span></div>
<pre class="code"><code><span class="t-keyword">for</span> attempt <span class="t-keyword">in</span> <span class="t-call">range</span>(<span class="t-number">1</span>, hook.attempts_max + <span class="t-number">1</span>):
    <span class="t-keyword">with</span> <span class="t-call">span</span>(<span class="t-string">"webhook.attempt"</span>, attempt=attempt) <span class="t-keyword">as</span> event:
        response = <span class="t-call">post</span>(hook.url, payload)
<span class="add">+       retryable = response.status &gt;= <span class="t-number">500</span></span>
<span class="add">+       event.<span class="t-call">set</span>(retryable=retryable,</span>
<span class="add">+                 will_retry=attempt &lt; hook.attempts_max)</span>
        <span class="t-keyword">if</span> response.ok: <span class="t-keyword">return</span></code></pre>
          </div>
          <div class="terminal-card agent" data-at="3">
            <div class="bar"><span class="who">claude · woken by Logika</span><span class="tag">your machine</span></div>
            <ol class="calls">
              ${call("Bash", "logika claim", "", 0.2)}
              <li class="output" style="--d:.7s"><pre>#214 webhook.attempt: NOT will_retry OR retryable
  37 events · status 410 · retryable false · will_retry true</pre></li>
              ${call("Edit", "src/webhooks/deliver.py", "", 1.4)}
              <li class="diff" data-at="4" style="--d:.1s"><pre><span class="del">-  will_retry=attempt &lt; hook.attempts_max)</span>
<span class="add">+  will_retry=retryable and attempt &lt; hook.attempts_max)</span></pre></li>
              ${call("Bash", "git commit -m \"Webhooks stop retrying a delivery that failed for good\"", "", 0.8, 'data-at="4"')}
              ${call("Bash", "logika resolve '{\"root_cause\": \"…\", \"items\": […]}'", "", 1.5, 'data-at="4"')}
            </ol>
          </div>
        </div>
        <div class="right">
          <div class="sheet commit" data-until="1">
            <span class="label">git log</span>
            <p><strong>Webhooks retry a failed delivery</strong></p>
            <p class="gate"><span class="pill guard-pill">the gate passed</span> <time>2m</time></p>
          </div>
          <div class="sheet map" data-at="1" data-until="2">
            <span class="label">logika map src/webhooks</span>
            <p class="line"><code>deliver</code> logs <code>webhook.attempt</code></p>
            <p class="risk"><code>webhooks.retry</code> by <code>attempt</code>, <code>will_retry</code> <span class="pill open-pill" style="--d:.2s">no rule yet</span></p>
<pre class="code" style="--d:1.2s"><code><span class="t-comment">// logika.json</span>
{<span class="t-key">"name"</span>: <span class="t-string">"attempt"</span>,
 <span class="t-key">"params"</span>: [<span class="t-string">"attempt"</span>, <span class="t-string">"retryable"</span>, <span class="t-string">"will_retry"</span>],
 <span class="t-key">"risks"</span>: {<span class="t-key">"webhooks.retry"</span>: [<span class="t-string">"attempt"</span>, <span class="t-string">"will_retry"</span>]},
<span class="add"> <span class="t-key">"validate"</span>: <span class="t-string">"NOT will_retry OR retryable"</span></span>}</code></pre>
            <p class="guarded" style="--d:2.2s"><span class="pill guard-pill">guarded by validate</span></p>
          </div>
          <div class="sheet production" data-at="2" data-until="4">
            <span class="label">production · webhook.attempt</span>
            <ol class="events">
              <li style="--d:.1s"><span>attempt 1</span><span>status 410</span><span>will_retry true</span></li>
              <li style="--d:.5s"><span>attempt 2</span><span>status 410</span><span>will_retry true</span></li>
              <li style="--d:.9s"><span>attempt 3</span><span>status 410</span><span>will_retry true</span></li>
              <li class="broken" style="--d:1.3s"><span>breaks</span><span>NOT will_retry OR retryable</span></li>
            </ol>
          </div>
          <div class="sheet issue" data-at="3">
            <div class="mail-head"><span class="from">Logika</span><time>4m</time></div>
            <strong class="subject">webhook.attempt: NOT will_retry OR retryable</strong>
            <p class="evidence">37 events in production since 14:02: a delivery answered 410 Gone, retried as if it would succeed.</p>
            <p class="woke" style="--d:.6s"><span class="pill guard-pill">your agent took it</span></p>
            <div class="reply" data-at="4" style="--d:1.9s"><strong>Re: fixed</strong><p>Retries stop on a permanent failure; the rule holds on replay.</p></div>
            <a class="more" href="https://logika.host" data-at="4" style="--d:2.4s">See Logika ${ICON.out}</a>
          </div>
        </div>
      </div>`,
    },
  };

  const reduced = matchMedia("(prefers-reduced-motion: reduce)");

  // A stage: its scenes' screens, the caption, the controls; one scene shown at one step.
  class Stage {
    constructor(root) {
      this.root = root;
      this.names = root.dataset.demo.split(/\s+/).filter(name => SCENES[name]);
      this.scene = this.names[0];
      this.step = 0;
      this.playing = false;
      this.timer = 0;
      this.listeners = [];
      root.classList.add("demo-stage");
      root.innerHTML = `<div class="demo-window">${this.names.map(name =>
        `<div class="screen" data-scene="${name}" aria-hidden="true" hidden>${SCENES[name].markup()}</div>`).join("")}</div>
        <div class="demo-foot">
          <p class="caption" aria-live="polite"><span class="count"></span><span class="text"></span></p>
          <div class="demo-controls" role="group" aria-label="The demo">
            <button type="button" data-do="replay" aria-label="Replay" title="Replay">${ICON.replay}</button>
            <button type="button" data-do="back" aria-label="The step before" title="The step before">${ICON.back}</button>
            <button type="button" data-do="toggle" class="primary" aria-label="Play" title="Play">${ICON.play}</button>
            <button type="button" data-do="next" aria-label="The next step" title="The next step">${ICON.next}</button>
            <span class="dots" aria-hidden="true"></span>
          </div>
        </div>`;
      this.caption = root.querySelector(".caption .text");
      this.count = root.querySelector(".caption .count");
      this.dots = root.querySelector(".dots");
      this.toggleButton = root.querySelector('[data-do="toggle"]');
      root.querySelector(".demo-controls").addEventListener("click", event => {
        const button = event.target.closest("button[data-do]");
        const dot = event.target.closest("[data-dot]");
        if (dot) { this.pause(); this.show(this.scene, Number(dot.dataset.dot)); return; }
        if (!button) return;
        const action = button.dataset.do;
        if (action === "toggle") this.playing ? this.pause() : this.play();
        if (action === "replay") { this.show(this.scene, 0); this.play(); }
        if (action === "back") { this.pause(); this.show(this.scene, Math.max(0, this.step - 1)); }
        if (action === "next") { this.pause(); this.show(this.scene, Math.min(this.last(), this.step + 1)); }
      });
      root.addEventListener("keydown", event => {
        if (event.target.closest("input, textarea")) return;
        if (event.key === "ArrowRight") { this.pause(); this.show(this.scene, Math.min(this.last(), this.step + 1)); }
        if (event.key === "ArrowLeft") { this.pause(); this.show(this.scene, Math.max(0, this.step - 1)); }
      });
      this.show(this.scene, 0);
    }

    last() { return SCENES[this.scene].steps.length - 1; }

    show(scene, step) {
      this.scene = scene;
      this.step = step;
      for (const screen of this.root.querySelectorAll(".screen")) {
        const shown = screen.dataset.scene === scene;
        screen.hidden = !shown;
        if (shown) draw(screen, step);
      }
      const steps = SCENES[scene].steps;
      this.caption.textContent = steps[step].caption;
      this.count.textContent = `${step + 1}/${steps.length}`;
      this.dots.innerHTML = steps.map((_, index) =>
        `<button type="button" data-dot="${index}" aria-label="Step ${index + 1}"${index === step ? ' aria-current="step"' : ""}${index < step ? ' class="done"' : ""}></button>`).join("");
      this.root.dataset.scene = scene;
      for (const listener of this.listeners) listener(scene, step);
    }

    play() {
      if (this.step >= this.last()) this.show(this.scene, 0);
      this.playing = true;
      this.mark();
      this.schedule();
    }

    pause() {
      this.playing = false;
      clearTimeout(this.timer);
      this.mark();
    }

    schedule() {
      clearTimeout(this.timer);
      if (!this.playing) return;
      this.timer = setTimeout(() => {
        if (this.step < this.last()) { this.show(this.scene, this.step + 1); this.schedule(); }
        else { this.pause(); this.ended?.(this.scene); }
      }, SCENES[this.scene].steps[this.step].hold);
    }

    mark() {
      this.toggleButton.innerHTML = this.playing ? ICON.pause : ICON.play;
      this.toggleButton.setAttribute("aria-label", this.playing ? "Pause" : "Play");
      this.toggleButton.title = this.playing ? "Pause" : "Play";
      this.root.classList.toggle("playing", this.playing);
    }
  }

  // A step drawn: each element shown from its step until its last, each class taken from its step.
  function draw(screen, step) {
    for (const element of screen.querySelectorAll("[data-at], [data-until]")) {
      const at = Number(element.dataset.at ?? 0);
      const until = element.dataset.until === undefined ? Infinity : Number(element.dataset.until);
      element.hidden = !(at <= step && step < until);
    }
    for (const element of screen.querySelectorAll("[data-on]")) {
      for (const pair of element.dataset.on.split(/\s+/)) {
        const [from, name] = pair.split(":");
        element.classList.toggle(name, step >= Number(from));
      }
      // A class a later step takes ends an earlier one of the same element.
      const pairs = element.dataset.on.split(/\s+/).map(pair => pair.split(":")).map(([from, name]) => [Number(from), name]);
      for (let index = 0; index < pairs.length - 1; index++) {
        if (step >= pairs[index + 1][0]) element.classList.remove(pairs[index][1]);
      }
    }
    screen.className = "screen " + Array.from({ length: step + 1 }, (_, index) => `s${index}`).join(" ");
  }

  // A still: one scene at one step, no controls, for a figure (data-demo-still="review:3").
  function still(figure) {
    const [name, step] = figure.dataset.demoStill.split(":");
    if (!SCENES[name]) return;
    figure.classList.add("demo-still");
    figure.innerHTML = `<div class="demo-window"><div class="screen" data-scene="${name}" aria-hidden="true">${SCENES[name].markup()}</div></div>`;
    draw(figure.querySelector(".screen"), Number(step));
    for (const animated of figure.querySelectorAll("[style*='--d']")) animated.style.setProperty("--d", "0s");
  }

  // Plays a stage while it is in view, unless motion is reduced or the visitor took over.
  function autoplay(stage) {
    if (reduced.matches) return;
    let touched = false;
    stage.root.addEventListener("click", () => { touched = true; }, { capture: true });
    new IntersectionObserver(entries => {
      for (const entry of entries) {
        if (entry.isIntersecting && !touched && !stage.playing) stage.play();
        if (!entry.isIntersecting && stage.playing) stage.pause();
      }
    }, { threshold: 0.45 }).observe(stage.root);
  }

  // Tabs beside a stage of several scenes: a tab shows its scene from its start, and its copy; once
  // a scene has played to its end, the next tab's plays, until the visitor takes over.
  function tabs(stage, group) {
    const buttons = [...group.querySelectorAll("[data-tab]")];
    const panels = [...document.querySelectorAll(`[data-panel-for="${group.dataset.tabsFor}"]`)];
    let held = false;
    const choose = (name, focus) => {
      for (const button of buttons) {
        const chosen = button.dataset.tab === name;
        button.setAttribute("aria-selected", String(chosen));
        button.tabIndex = chosen ? 0 : -1;
        if (chosen && focus) button.focus();
      }
      for (const panel of panels) panel.hidden = panel.dataset.panel !== name;
      stage.show(name, 0);
    };
    group.addEventListener("click", event => {
      const button = event.target.closest("[data-tab]");
      if (!button) return;
      held = true;
      choose(button.dataset.tab, false);
      if (!reduced.matches) stage.play();
    });
    group.addEventListener("keydown", event => {
      const index = buttons.findIndex(button => button.getAttribute("aria-selected") === "true");
      const move = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
      if (!move) return;
      event.preventDefault();
      held = true;
      choose(buttons[(index + move + buttons.length) % buttons.length].dataset.tab, true);
    });
    stage.root.addEventListener("click", () => { held = true; }, { capture: true });
    stage.ended = scene => {
      if (held) return;
      const next = buttons[(buttons.findIndex(button => button.dataset.tab === scene) + 1) % buttons.length];
      setTimeout(() => { if (!held) { choose(next.dataset.tab, false); stage.play(); } }, 900);
    };
    choose(buttons[0].dataset.tab, false);
    autoplay(stage);
  }

  // Beats in the copy, each a step of a scene: the one crossing the middle of the screen is shown.
  function beats(stage) {
    for (const list of document.querySelectorAll("[data-beats]")) {
      const name = list.dataset.beats;
      list.innerHTML = SCENES[name].steps.map((step, index) =>
        `<li class="beat" data-scene="${name}" data-step="${index}"><span class="count">${index + 1}/${SCENES[name].steps.length}</span><p>${step.caption}</p></li>`).join("");
    }
    const all = [...document.querySelectorAll(".beat")];
    stage.listeners.push((scene, step) => {
      for (const beat of all) beat.classList.toggle("current", beat.dataset.scene === scene && Number(beat.dataset.step) === step);
    });
    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        stage.pause();
        stage.show(entry.target.dataset.scene, Number(entry.target.dataset.step));
      }
    }, { rootMargin: "-48% 0px -48% 0px" });
    for (const beat of all) {
      observer.observe(beat);
      beat.addEventListener("click", () => { stage.pause(); stage.show(beat.dataset.scene, Number(beat.dataset.step)); });
    }
    stage.show(stage.scene, 0);
  }

  // Getting started as a stepper: one step at a time, its number pills above.
  function stepper(root) {
    const steps = [...root.querySelectorAll(".step")];
    const rail = document.querySelector(`[data-stepper-rail="${root.id}"]`);
    if (!rail || !steps.length) return;
    rail.innerHTML = steps.map((step, index) =>
      `<button type="button" role="tab" data-go="${index}" aria-controls="${step.id}" aria-label="${step.querySelector("h2").textContent}"><span>${index + 1}</span><em>${step.querySelector("h2").textContent}</em></button>`).join("");
    const pager = root.parentElement.querySelector("[data-stepper-pager]");
    const go = (index, scroll) => {
      steps.forEach((step, at) => { step.hidden = at !== index; });
      for (const button of rail.querySelectorAll("[data-go]")) {
        const at = Number(button.dataset.go);
        button.setAttribute("aria-selected", String(at === index));
        button.classList.toggle("done", at < index);
      }
      if (pager) {
        pager.querySelector("[data-step-back]").disabled = index === 0;
        pager.querySelector("[data-step-next]").disabled = index === steps.length - 1;
        pager.querySelector(".where").textContent = `${index + 1} of ${steps.length}`;
        pager.dataset.at = String(index);
      }
      if (scroll) root.scrollIntoView({ block: "nearest" });
    };
    rail.addEventListener("click", event => {
      const button = event.target.closest("[data-go]");
      if (button) go(Number(button.dataset.go), false);
    });
    pager?.addEventListener("click", event => {
      const at = Number(pager.dataset.at);
      if (event.target.closest("[data-step-back]")) go(Math.max(0, at - 1), true);
      if (event.target.closest("[data-step-next]")) go(Math.min(steps.length - 1, at + 1), true);
    });
    root.classList.add("stepping");
    go(0, false);
  }

  // Getting started as a split scroll: the step crossing the middle shows its figure on the side.
  function figures(root) {
    const steps = [...root.querySelectorAll(".step")];
    const side = document.querySelector(`[data-figures-for="${root.id}"]`);
    if (!side) return;
    side.innerHTML = steps.map(step => {
      const figure = step.querySelector("figure");
      return `<div class="side-figure" data-for="${step.id}">${figure ? figure.outerHTML : ""}</div>`;
    }).join("");
    for (const figure of side.querySelectorAll("[data-demo-still]")) still(figure);
    const show = id => {
      for (const figure of side.querySelectorAll(".side-figure")) figure.classList.toggle("current", figure.dataset.for === id);
      for (const step of steps) step.classList.toggle("current", step.id === id);
    };
    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) if (entry.isIntersecting) show(entry.target.id);
    }, { rootMargin: "-40% 0px -55% 0px" });
    for (const step of steps) observer.observe(step);
    root.classList.add("split-figures");
    show(steps[0].id);
  }

  // A page's sections, the one in view marked in its rail.
  function rail(nav) {
    const links = [...nav.querySelectorAll('a[href^="#"]')];
    const sections = links.map(link => document.getElementById(link.getAttribute("href").slice(1))).filter(Boolean);
    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        for (const link of links) link.toggleAttribute("aria-current", link.getAttribute("href") === `#${entry.target.id}`);
      }
    }, { rootMargin: "-30% 0px -60% 0px" });
    for (const section of sections) observer.observe(section);
  }

  function start() {
    for (const figure of document.querySelectorAll(".step [data-demo-still]")) still(figure);
    for (const root of document.querySelectorAll("[data-demo]")) {
      const stage = new Stage(root);
      const group = document.querySelector(`[data-tabs-for="${root.id}"]`);
      if (group) tabs(stage, group);
      else if (root.hasAttribute("data-driven")) beats(stage);
      else if (root.hasAttribute("data-autoplay")) autoplay(stage);
    }
    for (const root of document.querySelectorAll("[data-stepper]")) stepper(root);
    for (const root of document.querySelectorAll("[data-figures]")) figures(root);
    for (const nav of document.querySelectorAll("[data-rail]")) rail(nav);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
