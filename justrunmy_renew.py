#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JustRunMy.app 自动登录与续期 (100% 免费纯自动化版)"""
import os
import re
import socket
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from seleniumbase import SB

LOGIN_URL = "https://justrunmy.app/id/Account/Login"
APP_URL = os.getenv("JUSTRUNMY_APP_URL", "").strip() or "https://justrunmy.app/panel/application/39529/"
SCREENSHOT_DIR = Path(os.getenv("SCREENSHOT_DIR", "screenshots"))
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
ssh_process = None


def notify(message):
    token = os.getenv("TG_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TG_CHAT_ID", "").strip()
    if not token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": message}, timeout=15,
        ).raise_for_status()
        print("📩 Telegram 通知发送成功！")
    except Exception as exc:
        print(f"⚠️ Telegram 通知失败: {exc}")


def now_local():
    """GHA runner 係 UTC，通知統一顯示 UTC+8 嘅 MM-DD HH:MM。"""
    return (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%m-%d %H:%M")


def clip_text(text, limit=60):
    """壓成單行再截短，方便塞入一行通知。"""
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def app_label(path):
    """由 /panel/application/39529/ 抽短標籤，例如 app 39529。"""
    match = re.search(r"/application/(\d+)", path or "")
    return f"app {match.group(1)}" if match else (path or "?").strip("/") or "?"


def build_tg(items, failure=""):
    """方案 B (極致精簡人話版): 每台精準兩行，徹底消滅頂部計數器"""
    items = list(items or [])
    blocks = []
    for label, status, detail in items:
        name = f"JustRunMy（{label}）"
        if status.startswith("✅"):
            l1 = f"✅ {name} · 成功續期"
            l2 = "ℹ️ 服務已自動展期"
            blocks.append([l1, l2])
        elif status.startswith("❌"):
            l1 = f"🚨 {name} · 續期未完成"
            reason = clip_text(detail or "執行失敗", 60)
            l2 = f"⚠️ {reason} · 請登入面板手動處理"
            blocks.append([l1, l2])
        else: # ⏭️ / 狀態良好
            l1 = f"🟢 {name} · 狀態良好"
            info = clip_text(detail or "未到續期窗口", 60)
            l2 = f"ℹ️ {info}"
            blocks.append([l1, l2])

    if failure:
        blocks.append([
            "🚨 JustRunMy · 續期未完成",
            f"⚠️ {clip_text(failure, 60)} · 請登入面板手動處理"
        ])

    if not blocks:
        return "🟢 JustRunMy · 檢查完成（未發現應用實例）"

    return "\n\n".join("\n".join(b) for b in blocks)


def wait_port(port, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket() as sock:
            sock.settimeout(0.5)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.5)
    return False


def start_proxy():
    global ssh_process
    host = os.getenv("SSH_HOST", "").strip()
    user = os.getenv("SSH_USER", "").strip()
    password = os.getenv("SSH_PASS", "")
    port = os.getenv("SSH_PORT", "22").strip() or "22"
    socks_port = int(os.getenv("SOCKS_PORT", "51080"))
    if not host or not user:
        print("⚠️ 未配置 SSH 代理，使用直连")
        return None
    cmd = ["sshpass", "-p", password, "ssh", "-N", "-D", f"127.0.0.1:{socks_port}",
           "-p", port, "-o", "StrictHostKeyChecking=no", "-o", "ExitOnForwardFailure=yes",
           "-o", "ServerAliveInterval=30", f"{user}@{host}"]
    ssh_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if not wait_port(socks_port):
        err = ssh_process.stderr.read().decode("utf-8", "replace") if ssh_process.stderr else ""
        raise RuntimeError(f"SSH 动态隧道启动失败: {err[-500:]}")
    proxy = f"socks5://127.0.0.1:{socks_port}"
    print(f"✅ SSH 动态隧道已就绪: {proxy}")
    return proxy


def save_shot(sb, name):
    path = SCREENSHOT_DIR / name
    try:
        sb.save_screenshot(str(path))
        print(f"📸 截图已保存: {path}")
    except Exception as exc:
        print(f"⚠️ 截图保存失败: {exc}")


def first_visible(sb, selectors, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        for selector in selectors:
            try:
                if sb.is_element_visible(selector):
                    return selector
            except Exception:
                pass
        time.sleep(0.5)
    return None


def main():
    email = os.getenv("JUSTRUNMY_EMAIL", "").strip()
    password = os.getenv("JUSTRUNMY_PASSWORD", "")
    if not email or not password:
        raise RuntimeError("缺少 JUSTRUNMY_EMAIL 或 JUSTRUNMY_PASSWORD")
    
    proxy = start_proxy()
    kwargs = dict(uc=True, headless=False, locale="en-US")
    if proxy:
        kwargs["proxy"] = proxy

    with SB(**kwargs) as sb:
        try:
            # 1. 打开登录页
            sb.open(LOGIN_URL)
            sb.sleep(3)
            
            email_sel = first_visible(sb, ["input[type='email']", "input[name='Email']", "#Email"])
            pass_sel = first_visible(sb, ["input[type='password']", "input[name='Password']", "#Password"])
            if not email_sel or not pass_sel:
                raise RuntimeError("登录页面未找到邮箱或密码输入框")
            
            sb.type(email_sel, email)
            sb.type(pass_sel, password)
            sb.sleep(1)

            # 免费过 Cloudflare：调用 SeleniumBase 原生 UC 点击验证框
            try:
                sb.uc_gui_click_captcha()
                sb.sleep(3)
            except Exception:
                pass

            submit = first_visible(sb, ["button[type='submit']", "input[type='submit']"], 10)
            if not submit:
                raise RuntimeError("未找到登录按钮")
            sb.click(submit)
            sb.sleep(6)

            after_login_url = (sb.get_current_url() or "").lower()
            login_form_visible = bool(first_visible(
                sb, ["input[type='email']", "input[name='Email']", "#Email"], timeout=2
            ))
            if "/account/login" in after_login_url or login_form_visible:
                save_shot(sb, "login_not_completed.png")
                raise RuntimeError("登录未完成，停留在登录页（请检查账号密码或验证码）")

            print(f"✅ 登录成功: {sb.get_current_url()}")

            # 2. 打开 panel 抓取本账号全部 application
            sb.open("https://justrunmy.app/panel")
            sb.wait_for_ready_state_complete(timeout=30)
            sb.sleep(10)
            import re as _re
            src = sb.get_page_source() or ""
            with open(SCREENSHOT_DIR / "panel_dom.html", "w") as f:
                f.write(src)
            app_links = sorted(set(_re.findall(r'href="(/panel/application/\d+/?)"', src)))
            if not app_links:
                # Blazor 卡片無 anchor —— 直接點擊卡片導航，跟 current_url 攞 app URL
                app_links = []
                try:
                    # 等卡片 render（Blazor SignalR 接手 SSR DOM 需時）
                    for _ in range(30):
                        cnt = sb.execute_script("return document.querySelectorAll('h3[title]').length")
                        if isinstance(cnt, int) and cnt > 0:
                            break
                        sb.sleep(2)
                    card_count = sb.execute_script("return document.querySelectorAll('h3[title]').length")
                    print(f"🃏 panel 上有 {card_count} 張 app 卡片")
                    app_titles = sb.execute_script("""
                        return Array.from(document.querySelectorAll('h3[title]')).map(h => h.getAttribute('title'))
                    """) or []
                    print(f"🏷️ 卡片名: {app_titles}")
                    for i in range(int(card_count or 0)):
                        url_before = sb.get_current_url()
                        # 用 selenium 原生 click 第 i 張卡片標題（Blazor 會接手導航）
                        try:
                            sb.click(f'div.group h3[title]:nth-of-type({i+1})', timeout=8)
                        except Exception:
                            sb.execute_script(f"""
                                (() => {{
                                    let cards = document.querySelectorAll('h3[title]');
                                    if (cards[{i}]) cards[{i}].closest('.group')?.click();
                                }})()
                            """)
                        for _ in range(15):
                            sb.sleep(1)
                            url_now = sb.get_current_url() or ""
                            if url_now and url_now != url_before and "/panel" in url_now:
                                path = url_now.split("justrunmy.app")[-1].split("?")[0]
                                if path not in app_links:
                                    app_links.append(path)
                                    print(f"➡️ 卡片[{i}] 導航至: {path}")
                                break
                        # 返轉 panel 繼續掃下一張卡
                        if (sb.get_current_url() or "").endswith("/panel") is False:
                            sb.open("https://justrunmy.app/panel")
                            sb.sleep(6)
                except Exception as e:
                    print(f"⚠️ 卡片點擊導航失敗: {e}")
            print(f"📦 发现 {len(app_links)} 个 application: {app_links}")
            save_shot(sb, "panel_apps.png")
            if not app_links:
                app_links = [APP_URL.rstrip("/").split("justrunmy.app")[-1] or "/panel/application/39529/"]
                print("⚠️ panel 未发现 application 链接，fallback 用 APP_URL")

            items = []
            # 3. 逐个 application 走 Reset timer 流程
            for idx, path in enumerate(app_links, 1):
                app_url = f"https://justrunmy.app{path}"
                print(f"--- [{idx}/{len(app_links)}] 处理 {app_url} ---")
                try:
                    sb.open(app_url)
                    sb.wait_for_ready_state_complete(timeout=30)
                    sb.sleep(5)

                    # 关闭可能的弹窗
                    page_src = sb.get_page_source()
                    if "Application is stopped" in page_src:
                        print("▶️ 应用处于 Stopped，尝试点击 Start...")
                        exact_start = "//button[translate(normalize-space(text()), 'START', 'start')='start']"
                        try:
                            if sb.is_element_visible(exact_start):
                                sb.click(exact_start)
                                sb.sleep(5)
                        except Exception as e:
                            print(f"⚠️ Start 点击失败: {e}")

                    # 点击 Reset timer 打开弹窗
                    reset_xpath = ("//button[contains(translate(normalize-space(.), "
                                   "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'reset timer')]")
                    reset = first_visible(sb, [reset_xpath, "button:contains('Reset timer')"], 25)
                    if not reset:
                        save_shot(sb, f"renew_reset_btn_not_found_{idx}.png")
                        print(f"⚠️ [{idx}] 找不到 Reset timer 按钮，跳过")
                        items.append((app_label(path), "⏭️ 未可續", "無 Reset timer 按鈕"))
                        continue

                    sb.scroll_to(reset)
                    sb.click(reset)
                    sb.sleep(6)
                    save_shot(sb, f"renew_confirmation_opened_{idx}.png")

                    # 点击弹窗里的 Cloudflare 验证框
                    try:
                        sb.uc_gui_click_captcha()
                        sb.sleep(3)
                    except Exception as e:
                        print(f"⚠️ captcha click: {e}")

                    # 点击 Just Reset 按钮
                    confirm_xpath = ("//button[contains(translate(normalize-space(.), "
                                     "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'just reset')]")
                    confirm_btn = first_visible(sb, [confirm_xpath, "button:contains('Just Reset')"], 10)
                    if not confirm_btn:
                        save_shot(sb, f"confirm_btn_not_found_{idx}.png")
                        items.append((app_label(path), "❌ 續期未完成", "搵唔到 Just Reset 按鈕"))
                        continue

                    sb.click(confirm_btn)
                    sb.sleep(5)

                    save_shot(sb, f"renew_success_{idx}.png")
                    print(f"🎉 [{idx}] 自动续期指令已提交！")
                    items.append((app_label(path), "✅ 已續期", "Reset timer 已提交"))
                except Exception as exc:
                    save_shot(sb, f"renew_app_{idx}_failed.png")
                    print(f"❌ [{idx}] {path} 处理失败: {exc}")
                    items.append((app_label(path), "❌ 處理失敗", str(exc)))

            summary = build_tg(items)
            print(f"========== 全部结果 ==========\n{summary}")
            notify(summary)

        except Exception as exc:
            save_shot(sb, "renew_failed.png")
            notify(build_tg([], failure=str(exc)))
            raise
        finally:
            if ssh_process and ssh_process.poll() is None:
                ssh_process.terminate()


if __name__ == "__main__":
    main()
