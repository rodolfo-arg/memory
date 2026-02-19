from __future__ import annotations

from html import escape


def render_memory_graph_html(default_project_id: str = "") -> str:
    safe_project = escape(default_project_id, quote=True)
    html = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Memory Graph</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;700&family=Syne:wght@400;600;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg0: #0b1018;
      --bg1: #0f1622;
      --ink: #c8d6e5;
      --muted: #7d8d9e;
      --line: rgba(145, 168, 193, 0.24);
      --panel: rgba(12, 18, 27, 0.84);
      --accent: #85c2ff;
      --danger: #f17c89;
      --ok: #6fe0b3;
      --transition-fast: 150ms ease;
      --transition-base: 220ms ease;
      /* dashboard layout */
      --rail-w: 56px;
      --flyout-w: 264px;
      --drawer-w: 0px;
      --spring: cubic-bezier(0.16, 1, 0.3, 1);
      --surface: rgba(9, 13, 20, 0.94);
      --surface1: rgba(13, 18, 27, 0.92);
      --shadow-sm: 0 2px 8px rgba(0,0,0,0.4);
      --shadow-md: 0 4px 24px rgba(0,0,0,0.5);
      --shadow-lg: 0 8px 40px rgba(0,0,0,0.6);
    }
    * { box-sizing: border-box; }
    html, body {
      margin: 0;
      width: 100%;
      height: 100%;
      overflow: hidden;
      font-family: "IBM Plex Mono", ui-monospace, monospace;
      color: var(--ink);
      background:
        radial-gradient(circle at 16% 8%, rgba(119, 125, 255, 0.18), transparent 32%),
        radial-gradient(circle at 86% 86%, rgba(93, 156, 255, 0.16), transparent 34%),
        linear-gradient(160deg, var(--bg0), var(--bg1));
    }
    /* Graph canvas fills space between rail and drawer */
    #graph {
      position: fixed;
      inset: 0 var(--drawer-w) 0 var(--rail-w);
      z-index: 1;
    }
    #graph .scene-container,
    #graph canvas {
      width: 100%;
      height: 100%;
    }
    #graph canvas {
      display: block;
    }
    /* Panel base — shadow only, no border */
    .panel {
      position: fixed;
      z-index: 5;
      background: var(--panel);
      border-radius: 12px;
      backdrop-filter: blur(8px);
      box-shadow: var(--shadow-md);
      animation: panel-enter 240ms var(--transition-base) both;
    }
    /* Overlay keeps border for modal prominence */
    .overlay {
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      width: min(560px, calc(100vw - 28px));
      padding: 12px;
      z-index: 8;
      display: flex;
      flex-direction: column;
      gap: 8px;
      border: 1px solid var(--line);
    }
    .overlay.hidden {
      display: none;
    }
    /* Timeline panel */
    .timeline {
      position: fixed;
      z-index: 4;
      top: 8px;
      left: calc(var(--rail-w) + 8px);
      right: calc(var(--drawer-w) + 8px);
      bottom: 8px;
      padding: 10px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      overflow: hidden;
      background: var(--panel);
      border-radius: 12px;
      box-shadow: var(--shadow-md);
    }
    .timeline.hidden {
      display: none;
    }
    /* full-width in new layout still respects drawer */
    .timeline.full-width {
      right: calc(var(--drawer-w) + 8px);
    }
    /* Flyout open: shift graph and timeline left */
    [data-flyout-open] #graph {
      left: calc(var(--rail-w) + var(--flyout-w));
    }
    [data-flyout-open] .timeline {
      left: calc(var(--rail-w) + var(--flyout-w) + 8px);
    }
    .legacy-controls {
      display: none;
    }
    /* Drawer hidden — content preserved for JS refs */
    .drawer {
      display: none !important;
    }
    .drawer-kpis {
      padding: 16px 14px 12px;
      border-bottom: 1px solid var(--line);
      flex-shrink: 0;
    }
    .kpi-row {
      display: flex;
      gap: 20px;
      margin-bottom: 10px;
    }
    .kpi-block {
      display: flex;
      flex-direction: column;
      gap: 2px;
    }
    .kpi-big {
      font-size: 28px;
      font-weight: 700;
      color: #d8eaff;
      font-family: "Syne", "IBM Plex Mono", monospace;
      line-height: 1;
    }
    .kpi-unit {
      font-size: 10px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }
    .kpi-divider {
      height: 1px;
      background: var(--line);
      margin: 10px 0;
    }
    .kpi-row-grid {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 4px 10px;
    }
    .drawer-hint {
      padding: 10px 14px;
      border-bottom: 1px solid var(--line);
      flex-shrink: 0;
    }
    .drawer .error {
      padding: 6px 14px;
      flex-shrink: 0;
    }
    .drawer .details {
      flex: 1;
      min-height: 0;
      max-height: none;
      margin: 0 8px 8px;
      overflow: auto;
    }
    /* Inspector hidden: drawer stays, content fades */
    .inspector.hidden .details,
    .inspector.hidden .hint,
    .inspector.hidden .drawer-hint {
      visibility: hidden;
      opacity: 0;
    }
    /* Left navigation rail */
    .rail {
      position: fixed;
      inset: 0 auto 0 0;
      width: var(--rail-w);
      background: var(--surface);
      box-shadow: var(--shadow-sm);
      z-index: 7;
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: 8px 0;
      gap: 2px;
    }
    .rail-top, .rail-mid, .rail-bot {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 2px;
      width: 100%;
    }
    .rail-mid {
      flex: 1;
    }
    .rail-divider {
      width: 28px;
      height: 1px;
      background: var(--line);
      margin: 6px 0;
    }
    .rail-btn {
      width: 44px;
      height: 44px;
      border-radius: 10px;
      border: none;
      background: transparent;
      color: var(--muted);
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: background 120ms ease, color 120ms ease;
      position: relative;
    }
    .rail-btn:hover {
      background: rgba(133, 194, 255, 0.08);
      color: var(--ink);
    }
    .rail-btn.active {
      color: var(--accent);
      box-shadow: inset 2px 0 0 var(--accent);
    }
    .rail-btn:focus-visible {
      outline: none;
      box-shadow: 0 0 0 2px rgba(133, 194, 255, 0.4);
    }
    @keyframes pulse-ring {
      0%   { box-shadow: 0 0 0 0   rgba(133, 194, 255, 0.5); }
      70%  { box-shadow: 0 0 0 7px rgba(133, 194, 255, 0);   }
      100% { box-shadow: 0 0 0 0   rgba(133, 194, 255, 0);   }
    }
    .rail-btn.pulsing {
      color: var(--accent);
      animation: pulse-ring 1.6s ease-out infinite;
    }
    .rail-project-wrap {
      margin-top: auto;
      padding-bottom: 8px;
      overflow: hidden;
      max-height: 120px;
      display: flex;
      align-items: center;
      justify-content: center;
      width: 100%;
    }
    .rail-project-label {
      writing-mode: vertical-rl;
      transform: rotate(180deg);
      font-size: 9px;
      color: var(--muted);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      max-height: 110px;
      user-select: text;
      letter-spacing: 0.04em;
    }
    /* Flyout panels — slide in from rail */
    .flyout {
      position: fixed;
      left: var(--rail-w);
      top: 0;
      bottom: 0;
      width: var(--flyout-w);
      background: var(--surface1);
      box-shadow: var(--shadow-lg);
      z-index: 6;
      transform: translateX(-100%);
      transition: transform 180ms var(--spring);
      overflow-y: auto;
      display: flex;
      flex-direction: column;
    }
    .flyout.open {
      transform: translateX(0);
    }
    .flyout-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 14px 14px 10px;
      border-bottom: 1px solid var(--line);
      flex-shrink: 0;
      position: sticky;
      top: 0;
      background: var(--surface1);
      z-index: 1;
    }
    .flyout-title {
      font-family: "Syne", "IBM Plex Mono", monospace;
      font-size: 13px;
      font-weight: 700;
      color: #d8eaff;
    }
    .flyout-close {
      background: transparent;
      border: none;
      color: var(--muted);
      cursor: pointer;
      font-size: 14px;
      padding: 4px 6px;
      border-radius: 6px;
      transition: background 120ms ease, color 120ms ease;
    }
    .flyout-close:hover {
      background: rgba(133, 194, 255, 0.1);
      color: var(--ink);
    }
    .flyout-section {
      padding: 12px 14px;
      border-bottom: 1px solid rgba(145, 168, 193, 0.10);
    }
    .flyout-label {
      font-family: "Syne", "IBM Plex Mono", monospace;
      font-size: 10px;
      font-weight: 600;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.07em;
      margin-bottom: 8px;
    }
    .flyout-pill-row {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    .pill-btn {
      border: none;
      border-radius: 999px;
      padding: 5px 11px;
      background: rgba(145, 168, 193, 0.1);
      color: var(--muted);
      font: 500 11px "IBM Plex Mono", ui-monospace, monospace;
      cursor: pointer;
      transition: background 120ms ease, color 120ms ease;
    }
    .pill-btn:hover {
      background: rgba(133, 194, 255, 0.1);
      color: var(--ink);
    }
    .pill-btn.active {
      background: rgba(133, 194, 255, 0.15);
      color: var(--accent);
    }
    .flyout-slider {
      width: 100%;
      accent-color: var(--accent);
      cursor: pointer;
      display: block;
    }
    .flyout-slider-val {
      color: var(--muted);
      font-size: 11px;
      margin-top: 4px;
      text-align: right;
    }
    .flyout-date {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 6px 8px;
      background: rgba(8, 12, 18, 0.72);
      color: var(--ink);
      font: 500 11px "IBM Plex Mono", ui-monospace, monospace;
      outline: none;
    }
    .flyout-date:focus-visible {
      border-color: rgba(133, 194, 255, 0.7);
      box-shadow: 0 0 0 2px rgba(133, 194, 255, 0.2);
    }
    .flyout-toggle-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      font-size: 12px;
      color: var(--ink);
      cursor: pointer;
      gap: 8px;
    }
    .flyout-toggle-row input[type="checkbox"] {
      accent-color: var(--accent);
    }
    .flyout-select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 6px 8px;
      background: rgba(8, 12, 18, 0.72);
      color: var(--ink);
      font: 500 11px "IBM Plex Mono", ui-monospace, monospace;
      outline: none;
      margin-bottom: 8px;
    }
    .flyout-select:focus-visible {
      border-color: rgba(133, 194, 255, 0.7);
      box-shadow: 0 0 0 2px rgba(133, 194, 255, 0.2);
    }
    .flyout-btn-row {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
    }
    .flyout-action-btn {
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 5px 10px;
      background: rgba(14, 20, 30, 0.8);
      color: var(--ink);
      font: 600 11px "IBM Plex Mono", ui-monospace, monospace;
      cursor: pointer;
      transition: border-color 120ms ease, background 120ms ease;
    }
    .flyout-action-btn:hover {
      border-color: rgba(133, 194, 255, 0.6);
      background: rgba(133, 194, 255, 0.08);
    }
    .flyout-action-btn.danger {
      border-color: rgba(241, 124, 137, 0.4);
      color: var(--danger);
    }
    .flyout-action-btn.danger:hover {
      background: rgba(241, 124, 137, 0.1);
    }
    .flyout-input-num {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 6px 8px;
      background: rgba(8, 12, 18, 0.72);
      color: var(--ink);
      font: 500 11px "IBM Plex Mono", ui-monospace, monospace;
      outline: none;
    }
    .flyout-input-num:focus-visible {
      border-color: rgba(133, 194, 255, 0.7);
      box-shadow: 0 0 0 2px rgba(133, 194, 255, 0.2);
    }
    /* Inline search bar — expands from rail top */
    .search-bar {
      position: fixed;
      left: var(--rail-w);
      top: 0;
      height: 48px;
      width: 0;
      overflow: hidden;
      transition: width 180ms var(--spring);
      background: var(--surface);
      box-shadow: var(--shadow-md);
      z-index: 8;
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 0;
    }
    .search-bar.open {
      width: min(420px, 60vw);
      padding: 0 10px;
    }
    .search-input {
      flex: 1;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 6px 9px;
      background: rgba(8, 12, 18, 0.72);
      color: var(--ink);
      font: 500 12px "IBM Plex Mono", ui-monospace, monospace;
      outline: none;
      min-width: 0;
    }
    .search-input:focus-visible {
      border-color: rgba(133, 194, 255, 0.7);
      box-shadow: 0 0 0 2px rgba(133, 194, 255, 0.2);
    }
    .search-nav-btn, .search-clear-btn {
      background: transparent;
      border: 1px solid var(--line);
      border-radius: 6px;
      color: var(--muted);
      padding: 4px 7px;
      cursor: pointer;
      font-size: 12px;
      white-space: nowrap;
      flex-shrink: 0;
      transition: border-color 120ms ease, color 120ms ease;
    }
    .search-nav-btn:hover, .search-clear-btn:hover {
      border-color: rgba(133, 194, 255, 0.5);
      color: var(--ink);
    }
    .search-meta {
      font-size: 11px;
      color: var(--muted);
      white-space: nowrap;
      flex-shrink: 0;
    }
    /* Bottom status pill */
    .status-bar {
      position: fixed;
      bottom: 20px;
      left: 50%;
      transform: translateX(-50%);
      height: 32px;
      padding: 0 14px;
      border-radius: 999px;
      background: var(--surface);
      box-shadow: var(--shadow-md);
      z-index: 9;
      display: flex;
      align-items: center;
      gap: 8px;
      pointer-events: none;
    }
    .status-dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: var(--muted);
      flex-shrink: 0;
      transition: background 300ms ease;
    }
    .status-text {
      font-size: 11px;
      font-family: "Syne", "IBM Plex Mono", monospace;
      color: var(--muted);
      white-space: nowrap;
    }
    /* focus-visible for flyout/timeline inputs */
    .flyout input:focus-visible,
    .flyout select:focus-visible,
    .flyout button:focus-visible,
    .timeline-sort:focus-visible,
    .timeline-summary:focus-visible,
    .timeline-jump:focus-visible {
      outline: none;
      border-color: rgba(133, 194, 255, 0.86);
      box-shadow: 0 0 0 2px rgba(133, 194, 255, 0.24);
    }
    /* Timeline reactive mounting */
    .timeline-reactive-active .timeline-fallback-shell {
      display: none;
    }
    .timeline-reactive-root {
      height: 100%;
      min-height: 0;
    }
    .timeline-app-shell {
      display: flex;
      flex-direction: column;
      gap: 8px;
      height: 100%;
      min-height: 0;
    }
    .timeline-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 8px 10px;
      background: rgba(8, 12, 18, 0.72);
    }
    .timeline-title {
      color: #d8eaff;
      font-size: 12px;
      font-weight: 700;
    }
    .timeline-head-right {
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
    }
    .timeline-meta {
      color: var(--muted);
      font-size: 11px;
    }
    .timeline-refresh {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 6px 10px;
      min-height: 32px;
      background: rgba(10, 16, 24, 0.86);
      color: var(--ink);
      font: 600 11px "IBM Plex Mono", ui-monospace, monospace;
      cursor: pointer;
      transition: border-color var(--transition-fast), transform var(--transition-fast);
    }
    .timeline-refresh:hover {
      border-color: rgba(133, 194, 255, 0.72);
      transform: translateY(-1px);
    }
    .timeline-toolbar {
      border: 1px solid var(--line);
      border-radius: 10px;
      background: rgba(8, 12, 18, 0.76);
      padding: 10px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .timeline-search-input {
      border: 1px solid var(--line);
      border-radius: 8px;
      min-height: 34px;
      padding: 7px 9px;
      background: rgba(10, 16, 24, 0.82);
      color: var(--ink);
      font: 500 12px "IBM Plex Mono", ui-monospace, monospace;
      outline: none;
      transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
    }
    .timeline-search-input::placeholder {
      color: rgba(170, 193, 218, 0.62);
    }
    .timeline-search-input:focus-visible,
    .timeline-refresh:focus-visible,
    .timeline-input-number:focus-visible,
    .timeline-input-date:focus-visible {
      outline: none;
      border-color: rgba(133, 194, 255, 0.86);
      box-shadow: 0 0 0 2px rgba(133, 194, 255, 0.24);
    }
    .timeline-filter-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
    }
    .timeline-toggle {
      border: 1px solid rgba(145, 168, 193, 0.24);
      border-radius: 8px;
      min-height: 34px;
      padding: 8px 9px;
      display: flex;
      align-items: center;
      gap: 8px;
      background: rgba(12, 18, 28, 0.84);
      font-size: 11px;
      color: #d4e8ff;
    }
    .timeline-toggle input {
      accent-color: #85c2ff;
    }
    .timeline-input-wrap {
      border: 1px solid rgba(145, 168, 193, 0.24);
      border-radius: 8px;
      min-height: 34px;
      padding: 6px 8px;
      display: flex;
      flex-direction: column;
      gap: 4px;
      background: rgba(12, 18, 28, 0.84);
      color: #cde3fb;
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .timeline-input-number,
    .timeline-input-date {
      border: 1px solid rgba(145, 168, 193, 0.28);
      border-radius: 6px;
      min-height: 30px;
      padding: 5px 7px;
      background: rgba(8, 12, 18, 0.82);
      color: var(--ink);
      font: 500 11px "IBM Plex Mono", ui-monospace, monospace;
      outline: none;
      transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
    }
    .timeline-chip-row {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 10px;
    }
    .timeline-chip {
      border: 1px solid rgba(145, 168, 193, 0.24);
      border-radius: 999px;
      padding: 3px 8px;
      background: rgba(13, 20, 30, 0.8);
      color: #bdd9f6;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      font-size: 10px;
    }
    .rx-list {
      border: 1px solid var(--line);
      border-radius: 10px;
      background: rgba(8, 12, 18, 0.78);
      overflow: auto;
      padding: 8px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      min-height: 0;
    }
    .rx-day {
      position: sticky;
      top: 0;
      z-index: 1;
      color: #bfdcff;
      font-size: 11px;
      font-weight: 700;
      padding: 6px 8px;
      border: 1px solid rgba(145, 168, 193, 0.2);
      border-radius: 8px;
      background: rgba(12, 18, 28, 0.94);
      margin-top: 2px;
    }
    .rx-card {
      border: 1px solid rgba(145, 168, 193, 0.24);
      border-left: 2px solid rgba(133, 194, 255, 0.8);
      border-radius: 9px;
      background: rgba(11, 16, 24, 0.78);
      padding: 10px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .rx-card[data-kind="conversation"] { border-left-color: rgba(101, 211, 187, 0.9); }
    .rx-card[data-kind="chunk"] { border-left-color: rgba(235, 139, 182, 0.9); }
    .rx-card[data-kind="fact"] { border-left-color: rgba(255, 210, 123, 0.9); }
    .rx-summary {
      display: flex;
      flex-direction: column;
      gap: 8px;
      cursor: pointer;
      outline: none;
    }
    .rx-summary:focus-visible {
      box-shadow: 0 0 0 2px rgba(133, 194, 255, 0.24);
      border-radius: 6px;
    }
    .rx-row {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }
    .rx-time {
      color: var(--muted);
      font-size: 11px;
      min-width: 88px;
    }
    .rx-kind {
      border: 1px solid rgba(145, 168, 193, 0.3);
      border-radius: 7px;
      padding: 3px 7px;
      font-size: 11px;
      color: #d0e7ff;
      text-transform: lowercase;
    }
    .rx-kind.conversation { border-color: rgba(101, 211, 187, 0.54); color: #8de9d2; }
    .rx-kind.chunk { border-color: rgba(235, 139, 182, 0.54); color: #f5b4d3; }
    .rx-kind.fact { border-color: rgba(255, 210, 123, 0.54); color: #ffe1a1; }
    .rx-label {
      color: #d9ecff;
      font-size: 13px;
      font-weight: 700;
      line-height: 1.35;
      word-break: break-word;
    }
    .rx-note {
      color: #b7d3ef;
      font-size: 12px;
      line-height: 1.4;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .rx-meta {
      color: var(--muted);
      font-size: 11px;
      line-height: 1.3;
      word-break: break-word;
    }
    .rx-expanded {
      border-top: 1px solid rgba(145, 168, 193, 0.2);
      padding-top: 8px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .rx-meta-grid {
      display: grid;
      grid-template-columns: auto 1fr;
      gap: 4px 8px;
    }
    .rx-meta-k { color: var(--muted); white-space: nowrap; font-size: 11px; }
    .rx-meta-v { color: #b9d6f4; word-break: break-word; font-size: 11px; }
    .rx-fulltext {
      border: 1px solid rgba(145, 168, 193, 0.24);
      border-radius: 8px;
      padding: 8px;
      background: rgba(8, 12, 18, 0.66);
      color: #c6e1fb;
      font-size: 11px;
      line-height: 1.45;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .rx-actions { display: flex; justify-content: flex-end; }
    .rx-jump {
      border: 1px solid rgba(133, 194, 255, 0.44);
      border-radius: 8px;
      min-height: 34px;
      padding: 6px 10px;
      background: rgba(12, 20, 30, 0.88);
      color: #d9edff;
      font: 600 11px "IBM Plex Mono", ui-monospace, monospace;
      cursor: pointer;
      transition: transform var(--transition-fast), border-color var(--transition-fast);
    }
    .rx-jump:hover {
      transform: translateY(-1px);
      border-color: rgba(133, 194, 255, 0.72);
    }
    .timeline-sort {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 6px 8px;
      min-height: 32px;
      background: rgba(10, 16, 24, 0.82);
      color: var(--ink);
      font: 500 11px "IBM Plex Mono", ui-monospace, monospace;
      outline: none;
      transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
    }
    .timeline-list {
      border: 1px solid var(--line);
      border-radius: 10px;
      background: rgba(8, 12, 18, 0.78);
      overflow: auto;
      padding: 8px;
      display: flex;
      flex-direction: column;
      gap: 6px;
      min-height: 0;
    }
    .timeline-empty {
      color: var(--muted);
      font-size: 11px;
      padding: 10px 8px;
    }
    .timeline-day {
      position: sticky;
      top: 0;
      z-index: 1;
      color: #bfdcff;
      font-size: 11px;
      font-weight: 700;
      padding: 6px 8px;
      border: 1px solid rgba(145, 168, 193, 0.2);
      border-radius: 8px;
      background: rgba(12, 18, 28, 0.94);
      margin-top: 2px;
    }
    .timeline-item {
      border: 1px solid rgba(145, 168, 193, 0.22);
      border-radius: 9px;
      background: rgba(11, 16, 24, 0.72);
      display: flex;
      flex-direction: column;
      gap: 0;
      text-align: left;
      color: inherit;
      position: relative;
      overflow: hidden;
      min-height: 0;
      transition: transform var(--transition-fast), border-color var(--transition-fast), background var(--transition-fast);
      animation: item-enter 180ms var(--transition-fast) both;
    }
    .timeline-item::before {
      content: "";
      position: absolute;
      inset: 0 auto 0 0;
      width: 2px;
      background: rgba(133, 194, 255, 0.66);
    }
    .timeline-item[data-kind="conversation"]::before { background: rgba(101, 211, 187, 0.86); }
    .timeline-item[data-kind="chunk"]::before { background: rgba(235, 139, 182, 0.86); }
    .timeline-item[data-kind="fact"]::before { background: rgba(255, 210, 123, 0.86); }
    .timeline-item:hover {
      border-color: rgba(133, 194, 255, 0.54);
      transform: translateY(-1px);
      background: rgba(14, 20, 31, 0.8);
    }
    .timeline-item.expanded {
      border-color: rgba(133, 194, 255, 0.66);
      background: rgba(14, 22, 34, 0.86);
    }
    .timeline-summary {
      line-height: 1.35;
      text-align: left;
      cursor: pointer;
      padding: 10px 10px 8px 10px;
      display: block;
      min-height: 0;
      width: 100%;
      background: transparent;
      border: 0;
      color: inherit;
      font: inherit;
    }
    .timeline-expanded {
      padding: 0 8px 8px 8px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .timeline-fulltext {
      border: 1px solid rgba(145, 168, 193, 0.24);
      border-radius: 8px;
      padding: 8px;
      background: rgba(8, 12, 18, 0.66);
      color: #c6e1fb;
      font-size: 11px;
      line-height: 1.45;
      white-space: pre-wrap;
      word-break: break-word;
      max-height: none;
      overflow: visible;
    }
    .timeline-actions { display: flex; justify-content: flex-end; }
    .timeline-jump {
      border: 1px solid rgba(133, 194, 255, 0.44);
      border-radius: 8px;
      min-height: 34px;
      padding: 6px 10px;
      background: rgba(12, 20, 30, 0.88);
      color: #d9edff;
      font: 600 11px "IBM Plex Mono", ui-monospace, monospace;
      cursor: pointer;
      transition: transform var(--transition-fast), border-color var(--transition-fast);
    }
    .timeline-jump:hover {
      transform: translateY(-1px);
      border-color: rgba(133, 194, 255, 0.72);
    }
    .timeline-row {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }
    .timeline-time { color: var(--muted); font-size: 11px; min-width: 88px; }
    .timeline-kind {
      border: 1px solid rgba(145, 168, 193, 0.3);
      border-radius: 7px;
      padding: 3px 7px;
      font-size: 11px;
      color: #d0e7ff;
      text-transform: lowercase;
    }
    .timeline-kind.conversation { border-color: rgba(101, 211, 187, 0.54); color: #8de9d2; }
    .timeline-kind.chunk { border-color: rgba(235, 139, 182, 0.54); color: #f5b4d3; }
    .timeline-kind.fact { border-color: rgba(255, 210, 123, 0.54); color: #ffe1a1; }
    .timeline-label {
      color: #d9ecff;
      font-size: 13px;
      font-weight: 700;
      line-height: 1.35;
      word-break: break-word;
    }
    .timeline-note {
      color: #b7d3ef;
      font-size: 12px;
      line-height: 1.4;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .timeline-meta-row {
      color: var(--muted);
      font-size: 11px;
      line-height: 1.3;
      word-break: break-word;
    }
    .timeline-note[hidden],
    .timeline-meta-row[hidden],
    .timeline-expanded[hidden],
    .timeline-fulltext[hidden] {
      display: none !important;
    }
    .overlay-title { color: #e2f2ff; font-size: 13px; font-weight: 700; }
    .overlay-body {
      color: var(--muted);
      line-height: 1.45;
      font-size: 11px;
      white-space: pre-wrap;
    }
    /* Detail content elements */
    .grid {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 6px 10px;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 8px 9px;
      background: rgba(8, 12, 18, 0.72);
    }
    .k { color: var(--muted); font-size: 11px; }
    .v { color: #d2e5f9; font-size: 11px; font-weight: 700; }
    .hint {
      color: var(--muted);
      font-size: 11px;
      line-height: 1.4;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 8px 9px;
      background: rgba(8, 12, 18, 0.64);
    }
    .error { color: var(--danger); font-size: 11px; white-space: pre-wrap; }
    .details {
      margin: 0;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: rgba(8, 12, 18, 0.86);
      color: #9ecbff;
      overflow: auto;
      padding: 8px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      font-size: 11px;
    }
    .details-card {
      border: 1px solid rgba(145, 168, 193, 0.18);
      border-radius: 8px;
      padding: 8px;
      background: rgba(11, 16, 24, 0.74);
    }
    .details-title {
      color: #d9ebff;
      font-size: 11px;
      font-weight: 700;
      margin-bottom: 6px;
      word-break: break-word;
    }
    .meta-grid { display: grid; grid-template-columns: auto 1fr; gap: 4px 8px; }
    .meta-k { color: var(--muted); white-space: nowrap; }
    .meta-v { color: #b9d6f4; word-break: break-word; }
    .details-heading { color: #d4e7fb; font-weight: 700; margin-bottom: 6px; }
    .param-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(158px, 1fr)); gap: 6px; }
    .param-chip {
      border: 1px solid rgba(145, 168, 193, 0.2);
      border-radius: 7px;
      padding: 6px;
      background: rgba(16, 24, 34, 0.7);
      display: flex;
      flex-direction: column;
      gap: 2px;
      min-width: 0;
    }
    .param-k { color: var(--muted); font-size: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .param-v { color: #a6d4ff; font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .note-block {
      color: #c2ddf7;
      line-height: 1.45;
      white-space: pre-wrap;
      word-break: break-word;
      max-height: 220px;
      overflow: auto;
    }
    /* Floating node details popover */
    .node-popover {
      position: fixed;
      z-index: 20;
      background: var(--surface1);
      border: 1px solid rgba(133, 194, 255, 0.18);
      border-radius: 12px;
      box-shadow: var(--shadow-lg);
      width: 300px;
      max-height: 52vh;
      overflow-y: auto;
      display: none;
      flex-direction: column;
      pointer-events: all;
      backdrop-filter: blur(8px);
    }
    .node-popover.visible {
      display: flex;
      animation: panel-enter 160ms var(--spring) both;
    }
    .node-popover-header {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 10px 12px 8px;
      border-bottom: 1px solid var(--line);
      flex-shrink: 0;
      position: sticky;
      top: 0;
      background: var(--surface1);
      z-index: 1;
    }
    .node-popover-kind {
      font-size: 10px;
      padding: 2px 7px;
      border-radius: 999px;
      flex-shrink: 0;
      text-transform: lowercase;
    }
    .node-popover-kind.conversation { background: rgba(101, 211, 187, 0.15); color: #8de9d2; }
    .node-popover-kind.chunk       { background: rgba(235, 139, 182, 0.15); color: #f5b4d3; }
    .node-popover-kind.fact        { background: rgba(255, 210, 123, 0.15); color: #ffe1a1; }
    .node-popover-kind.project     { background: rgba(133, 194, 255, 0.15); color: var(--accent); }
    .node-popover-title {
      font-size: 12px;
      font-weight: 700;
      color: #d8eaff;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      flex: 1;
      min-width: 0;
    }
    .node-popover-close {
      background: transparent;
      border: none;
      color: var(--muted);
      cursor: pointer;
      font-size: 13px;
      padding: 3px 6px;
      border-radius: 5px;
      flex-shrink: 0;
      transition: background 120ms ease, color 120ms ease;
    }
    .node-popover-close:hover {
      background: rgba(133, 194, 255, 0.1);
      color: var(--ink);
    }
    .node-popover-body {
      padding: 10px 12px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .node-popover-note {
      border-top: 1px solid var(--line);
      padding-top: 8px;
    }
    .node-popover-note-label {
      font-size: 10px;
      font-weight: 600;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.06em;
      margin-bottom: 4px;
    }
    @keyframes panel-enter {
      from { opacity: 0; transform: translateY(8px); }
      to   { opacity: 1; transform: translateY(0); }
    }
    @keyframes item-enter {
      from { opacity: 0; transform: translateY(4px); }
      to   { opacity: 1; transform: translateY(0); }
    }
    @media (prefers-reduced-motion: reduce) {
      .panel, .timeline-item, .rail-btn.pulsing {
        animation: none !important;
        transition: none !important;
      }
    }
    @media (max-width: 900px) {
      :root { --flyout-w: 220px; }
      .timeline-filter-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    @media (max-width: 620px) {
      .timeline-filter-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <!-- Graph canvas -->
  <div id="graph"></div>

  <!-- Left icon rail -->
  <nav id="rail" class="rail">
    <div class="rail-top">
      <button id="graphViewBtn" class="rail-btn active" title="Graph view" aria-pressed="true">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="5" r="2"/><circle cx="5" cy="19" r="2"/><circle cx="19" cy="19" r="2"/>
          <line x1="12" y1="7" x2="5" y2="17"/><line x1="12" y1="7" x2="19" y2="17"/>
        </svg>
      </button>
      <button id="listViewBtn" class="rail-btn" title="List view" aria-pressed="false">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/>
          <circle cx="3.5" cy="6" r="1.2"/><circle cx="3.5" cy="12" r="1.2"/><circle cx="3.5" cy="18" r="1.2"/>
        </svg>
      </button>
    </div>
    <div class="rail-divider"></div>
    <div class="rail-mid">
      <button id="railFilterBtn" class="rail-btn" title="Filters">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <line x1="4" y1="6" x2="20" y2="6"/><line x1="8" y1="12" x2="16" y2="12"/><line x1="11" y1="18" x2="13" y2="18"/>
        </svg>
      </button>
      <button id="railSearchBtn" class="rail-btn" title="Search (/)">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="11" cy="11" r="7"/><line x1="16.5" y1="16.5" x2="22" y2="22"/>
        </svg>
      </button>
      <button id="railLiveBtn" class="rail-btn" title="Live mode">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
        </svg>
      </button>
    </div>
    <div class="rail-divider"></div>
    <div class="rail-bot">
      <button id="loadBtn" class="rail-btn" title="Reload">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="1 4 1 10 7 10"/>
          <path d="M3.51 15a9 9 0 1 0 .49-3.9"/>
        </svg>
      </button>
      <button id="railSettingsBtn" class="rail-btn" title="Settings">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="3"/>
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
        </svg>
      </button>
    </div>
    <div class="rail-project-wrap">
      <div id="currentProject" class="rail-project-label">-</div>
    </div>
  </nav>

  <!-- Filter flyout -->
  <div id="filterFlyout" class="flyout" aria-label="Filters">
    <div class="flyout-header">
      <span class="flyout-title">Filters</span>
      <button class="flyout-close" id="filterFlyoutClose">✕</button>
    </div>
    <div class="flyout-section">
      <div class="flyout-label">Memory Types</div>
      <div class="flyout-pill-row">
        <button class="pill-btn active" id="pillConversations">Conversations</button>
        <button class="pill-btn active" id="pillChunks">Chunks</button>
        <button class="pill-btn active" id="pillFacts">Facts</button>
      </div>
    </div>
    <div class="flyout-section">
      <div class="flyout-label">Min Importance</div>
      <input class="flyout-slider" id="flyoutMinImportance" type="range" min="0" max="1" step="0.05" value="0" />
      <div class="flyout-slider-val" id="flyoutMinImportanceVal">0.00</div>
    </div>
    <div class="flyout-section">
      <div class="flyout-label">Min Confidence</div>
      <input class="flyout-slider" id="flyoutMinConfidence" type="range" min="0" max="1" step="0.05" value="0" />
      <div class="flyout-slider-val" id="flyoutMinConfidenceVal">0.00</div>
    </div>
    <div class="flyout-section">
      <div class="flyout-label">Created After</div>
      <input class="flyout-date" id="flyoutCreatedAfter" type="date" />
    </div>
    <div class="flyout-section">
      <label class="flyout-toggle-row">
        <span>Include Archived</span>
        <input type="checkbox" id="flyoutIncludeArchived" />
      </label>
    </div>
    <div class="flyout-section">
      <div class="flyout-label">Saved Views</div>
      <select id="viewPresetSelect" class="flyout-select"><option value="">— saved views —</option></select>
      <div class="flyout-btn-row">
        <button class="flyout-action-btn" id="applyViewBtn">Apply</button>
        <button class="flyout-action-btn" id="saveViewBtn">Save</button>
        <button class="flyout-action-btn danger" id="deleteViewBtn">Delete</button>
      </div>
    </div>
  </div>

  <!-- Settings flyout -->
  <div id="settingsFlyout" class="flyout" aria-label="Settings">
    <div class="flyout-header">
      <span class="flyout-title">Settings</span>
      <button class="flyout-close" id="settingsFlyoutClose">✕</button>
    </div>
    <div class="flyout-section">
      <div class="flyout-label">Max Conversations</div>
      <input class="flyout-input-num" id="flyoutMaxConversations" type="number" min="1" max="5000" value="180" />
    </div>
    <div class="flyout-section">
      <div class="flyout-label">Max Chunks</div>
      <input class="flyout-input-num" id="flyoutMaxChunks" type="number" min="1" max="20000" value="1200" />
    </div>
    <div class="flyout-section">
      <div class="flyout-label">Max Facts</div>
      <input class="flyout-input-num" id="flyoutMaxFacts" type="number" min="1" max="10000" value="800" />
    </div>
    <div class="flyout-section">
      <div class="flyout-label">Live Refresh (seconds)</div>
      <input class="flyout-input-num" id="flyoutLiveEverySec" type="number" min="1" max="120" value="4" />
    </div>
    <div class="flyout-section">
      <div class="flyout-label">Render Mode</div>
      <select id="flyoutRenderMode" class="flyout-select">
        <option value="auto">auto</option>
        <option value="2d">2d</option>
      </select>
    </div>
    <div class="flyout-section">
      <div class="flyout-label">Graph</div>
      <div class="flyout-btn-row">
        <button class="flyout-action-btn" id="collapseBtn">Collapse</button>
        <button class="flyout-action-btn" id="expandAllBtn">Expand All</button>
        <button class="flyout-action-btn" id="fitBtn">Fit</button>
      </div>
    </div>
  </div>

  <!-- Inline search bar (expands from rail top) -->
  <div id="searchBar" class="search-bar" role="search">
    <input id="searchInput" type="search" class="search-input" placeholder="Search memories…" />
    <button id="searchPrevBtn" class="search-nav-btn" title="Previous">↑</button>
    <button id="searchNextBtn" class="search-nav-btn" title="Next">↓</button>
    <button id="searchClearBtn" class="search-clear-btn" title="Clear">✕</button>
    <span id="searchMeta" class="search-meta"></span>
  </div>

  <!-- Right detail drawer (always visible) -->
  <aside id="drawer" class="drawer inspector" aria-label="Memory details">
    <div class="drawer-kpis">
      <div class="kpi-row">
        <div class="kpi-block">
          <span class="kpi-big" id="kpiNodes">0</span>
          <span class="kpi-unit">nodes</span>
        </div>
        <div class="kpi-block">
          <span class="kpi-big" id="kpiEdges">0</span>
          <span class="kpi-unit">edges</span>
        </div>
      </div>
      <div class="kpi-divider"></div>
      <div class="kpi-row-grid">
        <span class="k">Conversations</span><span class="v" id="kpiConversations">0</span>
        <span class="k">Chunks</span><span class="v" id="kpiChunks">0</span>
        <span class="k">Facts</span><span class="v" id="kpiFacts">0</span>
        <span class="k">Mode</span><span class="v" id="kpiMode">-</span>
        <span class="k">Live</span><span class="v" id="kpiLive">off</span>
        <span class="k">Updated</span><span class="v" id="kpiUpdated">-</span>
      </div>
    </div>
    <div class="drawer-hint hint">
      Click a node to expand neighbors. Live mode refreshes while preserving state.
    </div>
    <div id="error" class="error"></div>
    <div id="details" class="details"></div>
  </aside>

  <!-- Bottom status pill -->
  <div class="status-bar" aria-live="polite">
    <span class="status-dot" id="statusDot"></span>
    <span id="status" class="status-text">idle</span>
  </div>

  <!-- Error overlay (modal) -->
  <section id="overlay" class="panel overlay hidden">
    <div id="overlayTitle" class="overlay-title"></div>
    <div id="overlayBody" class="overlay-body"></div>
  </section>

  <!-- Timeline view -->
  <section id="timelineView" class="panel timeline hidden">
    <div class="timeline-fallback-shell">
      <div class="timeline-head">
        <div class="timeline-title">Memory Timeline</div>
        <div class="timeline-head-right">
          <select id="timelineSort" class="timeline-sort" aria-label="Timeline sort">
            <option value="desc">Newest</option>
            <option value="asc">Oldest</option>
          </select>
          <div id="timelineMeta" class="timeline-meta" aria-live="polite">0 items</div>
        </div>
      </div>
      <div id="timelineList" class="timeline-list" role="list"></div>
    </div>
  </section>

  <!-- Hidden legacy controls — all existing JS element IDs preserved -->
  <div class="legacy-controls" aria-hidden="true">
    <input id="projectId" type="text" value="__DEFAULT_PROJECT__" />
    <input id="maxConversations" type="number" min="1" max="5000" value="180" />
    <input id="maxChunks" type="number" min="1" max="20000" value="1200" />
    <input id="maxFacts" type="number" min="1" max="10000" value="800" />
    <input id="includeArchived" type="checkbox" />
    <select id="renderMode">
      <option value="auto">auto</option>
      <option value="2d">2d</option>
    </select>
    <select id="displayMode">
      <option value="graph">graph</option>
      <option value="list">timeline</option>
    </select>
    <input id="liveMode" type="checkbox" />
    <input id="liveEverySec" type="number" min="1" max="120" value="4" />
    <input id="showConversations" type="checkbox" checked />
    <input id="showChunks" type="checkbox" checked />
    <input id="showFacts" type="checkbox" checked />
    <input id="minImportance" type="number" min="0" max="1" step="0.05" />
    <input id="minConfidence" type="number" min="0" max="1" step="0.05" />
    <input id="createdAfter" type="date" />
  </div>

  <!-- Floating node details popover -->
  <div id="nodePopover" class="node-popover" role="tooltip" aria-hidden="true"></div>

  <script src="/ui/static/vendor/force-graph.min.js?v=20260218b"></script>
  <script src="/ui/static/vendor/vue.global.prod.js?v=20260218a"></script>
  <script src="/ui/static/memory-graph-list-app.js?v=20260218d"></script>
  <script src="/ui/static/memory-graph-ui.js?v=20260219b"></script>
</body>
</html>"""
    return html.replace("__DEFAULT_PROJECT__", safe_project)
