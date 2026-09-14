#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JustRunMy.app 自动登录与续期 (100% 免费纯自动化版)"""
import os
import socket
import subprocess
import time
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
            sb.sleep(4)
            import re as _re
            src = sb.get_page_source() or ""
            app_links = sorted(set(_re.findall(r'href="(/panel/application/\d+/?)"', src)))
            print(f"📦 发现 {len(app_links)} 个 application: {app_links}")
            save_shot(sb, "panel_apps.png")
            if not app_links:
                app_links = [APP_URL.rstrip("/").split("justrunmy.app")[-1] or "/panel/application/39529/"]
                print("⚠️ panel 未发现 application 链接，fallback 用 APP_URL")

            results = []
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
                        results.append(f"{path}: 无 Reset timer 按钮")
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
                        results.append(f"{path}: 无 Just Reset 按钮")
                        continue

                    sb.click(confirm_btn)
                    sb.sleep(5)

                    save_shot(sb, f"renew_success_{idx}.png")
                    print(f"🎉 [{idx}] 自动续期指令已提交！")
                    results.append(f"{path}: ✅ 续期提交成功")
                except Exception as exc:
                    save_shot(sb, f"renew_app_{idx}_failed.png")
                    print(f"❌ [{idx}] {path} 处理失败: {exc}")
                    results.append(f"{path}: ❌ {str(exc)[:80]}")

            summary = "\n".join(results)
            print(f"========== 全部结果 ==========\n{summary}")
            notify(f"✅ JustRunMy.app 续期完成：\n{summary}")

        except Exception as exc:
            save_shot(sb, "renew_failed.png")
            notify(f"❌ JustRunMy.app 自动续期失败: {exc}")
            raise
        finally:
            if ssh_process and ssh_process.poll() is None:
                ssh_process.terminate()


if __name__ == "__main__":
    main()
