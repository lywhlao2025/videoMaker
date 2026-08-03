(() => {
  if (document.querySelector("lywh-site-nav")) return;

  const host = document.createElement("lywh-site-nav");
  const shadow = host.attachShadow({ mode: "open" });
  const path = window.location.pathname;
  const items = [
    { href: "/chat/", label: "Chat", icon: "AI", active: path.startsWith("/chat") },
    {
      href: "/video/",
      // Keep the source ASCII-safe for proxies that ignore the response charset.
      label: "\u89c6\u9891\u751f\u6210",
      icon: "MV",
      active: path.startsWith("/video"),
    },
  ];

  shadow.innerHTML = `
    <style>
      :host {
        all: initial;
        position: fixed;
        inset: 0 0 auto 0;
        z-index: 2147483000;
        height: 54px;
        font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont,
          "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      }
      nav {
        height: 54px;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 0 16px;
        box-sizing: border-box;
        color: #dbeafe;
        background: rgba(8, 15, 30, 0.94);
        border-bottom: 1px solid rgba(148, 163, 184, 0.22);
        box-shadow: 0 8px 28px rgba(2, 6, 23, 0.2);
        backdrop-filter: blur(16px);
        -webkit-backdrop-filter: blur(16px);
      }
      .tabs {
        width: min(760px, 100%);
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 6px;
        overflow-x: auto;
        scrollbar-width: none;
      }
      .tabs::-webkit-scrollbar { display: none; }
      a {
        color: #cbd5e1;
        text-decoration: none;
        display: inline-flex;
        align-items: center;
        gap: 8px;
        min-height: 36px;
        padding: 0 14px;
        border-radius: 10px;
        font-size: 14px;
        font-weight: 650;
        line-height: 1;
        white-space: nowrap;
        transition: color 150ms ease, background 150ms ease, transform 150ms ease;
      }
      a:hover {
        color: #fff;
        background: rgba(59, 130, 246, 0.16);
        transform: translateY(-1px);
      }
      a.active {
        color: #fff;
        background: linear-gradient(135deg, #2563eb, #7c3aed);
        box-shadow: 0 5px 16px rgba(37, 99, 235, 0.3);
      }
      .icon {
        width: 22px;
        height: 22px;
        display: inline-grid;
        place-items: center;
        border-radius: 7px;
        font-size: 10px;
        font-weight: 800;
        letter-spacing: -0.02em;
        color: #dbeafe;
        background: rgba(148, 163, 184, 0.16);
      }
      a.active .icon { background: rgba(255, 255, 255, 0.2); color: #fff; }
      @media (max-width: 540px) {
        nav { justify-content: flex-start; padding: 0 8px; }
        .tabs { justify-content: flex-start; }
        a { gap: 6px; padding: 0 10px; font-size: 13px; }
        .icon { display: none; }
      }
    </style>
    <nav aria-label="\u7ad9\u70b9\u5bfc\u822a">
      <div class="tabs">
        ${items
          .map(
            (item) => `
              <a href="${item.href}" class="${item.active ? "active" : ""}"
                 ${item.active ? 'aria-current="page"' : ""}>
                <span class="icon">${item.icon}</span>
                <span>${item.label}</span>
              </a>`,
          )
          .join("")}
      </div>
    </nav>`;

  const pageStyle = document.createElement("style");
  pageStyle.id = "lywh-site-nav-offset";
  pageStyle.textContent = path.startsWith("/video")
    ? `
      html { scroll-padding-top: 54px !important; }
      body { padding-top: 0 !important; box-sizing: border-box !important; }
      #root {
        position: fixed !important;
        inset: 54px 0 0 0 !important;
        width: 100% !important;
        height: auto !important;
        min-height: 0 !important;
      }
    `
    : `
      html { scroll-padding-top: 54px !important; }
      body { padding-top: 54px !important; box-sizing: border-box !important; }
    `;
  document.head.appendChild(pageStyle);
  document.body.appendChild(host);
})();
