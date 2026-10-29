"""
Grim Soul 每日奖励 & 免费塔勒（Thaler）自动领取脚本
适配英文官网（Xsolla Site Builder，2026-10 新版登录界面）：
  - 每日奖励：https://grimsoul.com/rewards
  - 商店：    https://grimsoul.com/store
仅需在环境变量中提供 GRIMSOUL_ACCOUNT_ID（游戏账号 ID）。

新版登录有两种入口，脚本均支持：
  A. 主页内嵌的 "Log in with User ID" 区块（Enter your user ID + Log in）
  B. 右上角 Log in 按钮弹出的弹窗（Your user ID + Log in）
默认走 A，A 不存在时自动回退到 B。
"""
import os
import re
import sys
import time
import datetime
from playwright.sync_api import sync_playwright

# ===================== 配置 =====================
ACCOUNT_ID = os.environ.get("GRIMSOUL_ACCOUNT_ID")
BASE_URL = "https://grimsoul.com"
REWARDS_URL = f"{BASE_URL}/rewards"
STORE_URL = f"{BASE_URL}/store"

# 领取后的倒计时格式，如 "20h 17m"（不是旧版的 HH:MM:SS）
COUNTDOWN_RE = re.compile(r"\d{1,2}h\s*\d{1,2}m")

# 截图保存到脚本同级的 screenshots 目录
SCREENSHOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)


# ===================== 工具函数 =====================
def log(msg):
    print(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def screenshot(page, name):
    """截取当前领取界面（视口），用于失败或今日已领取（无弹窗）的情况"""
    try:
        path = os.path.join(SCREENSHOT_DIR, name)
        page.screenshot(path=path, full_page=False)
        log(f"已保存界面截图：{path}")
    except Exception as e:
        log(f"截图失败（{name}）：{e}")


def screenshot_dialog(page, name):
    """只截取领取成功弹窗（You got reward!）本身，成功时使用"""
    try:
        dialog = page.get_by_role("dialog").first
        dialog.wait_for(state="visible", timeout=5000)
        path = os.path.join(SCREENSHOT_DIR, name)
        dialog.screenshot(path=path)
        log(f"已保存成功弹窗截图：{path}")
        return True
    except Exception as e:
        log(f"弹窗截图失败（{name}）：{e}")
        return False


def goto(page, url, retries=3):
    """带重试的页面跳转"""
    for i in range(1, retries + 1):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_load_state("networkidle", timeout=30000)
            return True
        except Exception as e:
            log(f"访问 {url} 失败（第 {i}/{retries} 次）：{e}")
    return False


def accept_cookies(page):
    """关闭官网原生 Cookie 弹窗（Accept All / Reject All）"""
    for name in ("Accept All", "Reject All"):
        try:
            btn = page.get_by_role("button", name=name, exact=True).first
            if btn.is_visible():
                btn.click(timeout=3000)
                log(f"已关闭 Cookie 弹窗：{name}")
                page.wait_for_timeout(800)
                return True
        except Exception:
            continue
    return False


def dismiss_promo(page):
    """如出现促销弹窗，用关闭按钮关掉（仅在弹窗存在时操作）"""
    try:
        dialog = page.get_by_role("dialog")
        if dialog.count() > 0 and dialog.first.is_visible():
            close = dialog.get_by_test_id("close-icon").first
            if close.is_visible():
                close.click(timeout=2000)
                log("已关闭促销弹窗")
                page.wait_for_timeout(800)
                return True
    except Exception:
        pass
    return False


# ===================== 登录 =====================
def is_logged_in(page):
    """根据页面特征判断当前是否已登录。

    未登录的 rewards 页面同时存在：
      - 内嵌登录表单 [data-testid="fast-login"] 的输入框
      - "Log in to claim reward" 按钮
    两者都消失即视为已登录。
    """
    try:
        fast_input = page.locator('[data-testid="fast-login"] input').first
        fast_visible = fast_input.count() > 0 and fast_input.is_visible()
    except Exception:
        fast_visible = False
    try:
        need_login = page.get_by_role(
            "button", name="Log in to claim reward", exact=True
        ).first
        need_visible = need_login.count() > 0 and need_login.is_visible()
    except Exception:
        need_visible = False
    return not fast_visible and not need_visible


def has_invalid_id_error(page):
    """页面是否显示 'Enter a valid ID' 错误（两条登录入口共用同一提示文案）"""
    try:
        err = page.get_by_text("Enter a valid ID", exact=True).first
        return err.count() > 0 and err.is_visible()
    except Exception:
        return False


def wait_login_result(page, timeout=15000):
    """轮询等待登录结果：成功返回 True，ID 无效返回 False，超时返回 None"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if has_invalid_id_error(page):
            return False
        if is_logged_in(page):
            return True
        page.wait_for_timeout(500)
    return None


def login_via_inline_form(page):
    """入口 A：主页内嵌的 'Log in with User ID' 区块"""
    user_input = page.locator('[data-testid="fast-login"] input').first
    try:
        user_input.wait_for(state="visible", timeout=10000)
    except Exception:
        return False

    # 新版输入框直接可见，无需先点按钮展开；直接填 ID 并提交
    user_input.fill(ACCOUNT_ID)
    log("已在内嵌表单填写 User ID")
    page.locator('[data-testid="fast-login-button-authorization-user-id"]').first.click()
    log("已点击内嵌表单的 Log in")

    result = wait_login_result(page)
    if result is True:
        log("登录成功（内嵌表单）")
    elif result is False:
        log("登录失败：账号 ID 无效（Enter a valid ID）")
    else:
        log("登录结果未知：内嵌表单提交后页面无变化，请查看截图")
    return result


def login_via_modal(page):
    """入口 B：右上角 Log in 按钮弹出的弹窗"""
    # 右上角 Log in 按钮没有 testid，需排除内嵌表单的提交按钮
    try:
        trigger = page.locator(
            "button:not([data-testid='fast-login-button-authorization-user-id'])"
        ).filter(has_text="Log in").first
        trigger.wait_for(state="visible", timeout=10000)
        trigger.click()
        log("已点击右上角 Log in，等待弹窗")
    except Exception as e:
        log(f"未找到右上角 Log in 按钮：{e}")
        return False

    # 弹窗出现后在 dialog 内填写
    try:
        dialog = page.get_by_role("dialog").first
        dialog.wait_for(state="visible", timeout=10000)
        user_input = dialog.locator("input").first
        user_input.wait_for(state="visible", timeout=5000)
        user_input.fill(ACCOUNT_ID)
        log("已在登录弹窗填写 User ID")
        dialog.get_by_test_id("user-id-button-continue").click()
        log("已点击弹窗中的 Log in")
    except Exception as e:
        log(f"登录弹窗操作失败：{e}")
        return False

    result = wait_login_result(page)
    if result is True:
        log("登录成功（弹窗）")
    elif result is False:
        log("登录失败：账号 ID 无效（Enter a valid ID）")
    else:
        log("登录结果未知：弹窗提交后页面无变化，请查看截图")
    return result


def login(page):
    """用账号 ID 登录：优先内嵌表单，失败/不存在时回退到弹窗"""
    if not goto(page, REWARDS_URL):
        return False
    accept_cookies(page)
    dismiss_promo(page)

    # 可能已经是登录态（复用上下文等场景）
    if is_logged_in(page):
        log("页面已是登录态，无需重复登录")
        return True

    # 先尝试内嵌表单；仅当入口不存在（None / False 且无 ID 错误）时再走弹窗
    if page.locator('[data-testid="fast-login"] input').count() > 0:
        result = login_via_inline_form(page)
        if result is True:
            return True
        if result is False:
            # 明确是 ID 无效，换入口也无意义，直接失败
            return False
        log("内嵌表单登录未成功，尝试改用弹窗登录")

    return login_via_modal(page) is True


# ===================== 每日奖励 =====================
def claim_daily(page):
    if not goto(page, REWARDS_URL):
        return False
    accept_cookies(page)
    dismiss_promo(page)

    # 等待 Daily rewards 模块加载
    try:
        page.get_by_text("Daily rewards", exact=False).first.wait_for(
            state="visible", timeout=20000
        )
    except Exception:
        pass

    # 1) 已领取：下一天卡片出现倒计时（如 20h 17m），无弹窗，截当前界面
    timer = page.get_by_text(COUNTDOWN_RE).first
    if timer.count() > 0 and timer.is_visible():
        log("每日奖励：检测到倒计时，今日已领取")
        screenshot(page, "daily_rewards.png")
        return True

    # 2) 未领取：当日卡片上有 Claim 按钮
    claim = page.get_by_role("button", name="Claim", exact=True).first
    if claim.count() > 0 and claim.is_visible():
        claim.click()
        log("每日奖励：已点击 Claim")
        try:
            page.get_by_text("You got reward!", exact=False).first.wait_for(
                state="visible", timeout=10000
            )
            log("每日奖励：领取成功")
        except Exception:
            log("警告：未检测到领取成功弹窗，截取当前领取界面")
            screenshot(page, "daily_rewards.png")
            return False
        # 成功：只截成功弹窗，然后关闭（Back to store）
        screenshot_dialog(page, "daily_rewards.png")
        try:
            page.get_by_role("button", name="Back to store", exact=True).first.click(
                timeout=3000
            )
            log("已关闭奖励弹窗")
        except Exception:
            pass
        return True

    log("每日奖励：未找到 Claim 按钮，也没有倒计时，截取当前领取界面")
    screenshot(page, "daily_rewards.png")
    return False


# ===================== 商店免费塔勒 =====================
def claim_free_coins(page):
    if not goto(page, STORE_URL):
        return False
    accept_cookies(page)
    dismiss_promo(page)

    # 切到 Coins 标签
    try:
        tab = page.get_by_role("tab", name="Coins", exact=True)
        if tab.is_visible():
            tab.click()
            page.wait_for_timeout(1000)
    except Exception:
        pass

    # 定位 10 Thalers 卡片
    card = page.locator('[data-testid="new-store-card"]').filter(
        has_text="10 Thalers"
    ).first
    try:
        card.wait_for(state="visible", timeout=15000)
        card.scroll_into_view_if_needed()
        page.wait_for_timeout(500)
    except Exception:
        log("商店：未找到 10 Thalers 卡片")
        screenshot(page, "store.png")
        return False

    # 1) 已领取：按钮变 Owned（置灰）或出现倒计时，无弹窗，截当前界面
    if card.get_by_text(COUNTDOWN_RE).count() > 0 or card.get_by_role(
        "button", name="Owned", exact=True
    ).count() > 0:
        log("商店：今日免费塔勒已领取")
        screenshot(page, "store.png")
        return True

    # 2) 未领取：点击 Get free
    free = card.get_by_test_id("free-button")
    if free.is_visible() and free.is_enabled():
        free.click()
        log("商店：已点击 Get free")

        # 等待成功弹窗出现
        try:
            dialog = page.get_by_role("dialog")
            dialog.get_by_text("You got reward!", exact=False).first.wait_for(
                state="visible", timeout=10000
            )
        except Exception:
            log("警告：未检测到领取成功弹窗，截取当前领取界面")
            screenshot(page, "store.png")
            return False

        # 成功：只截成功弹窗（在点 Claim 确认之前），然后在弹窗中点击 Claim
        screenshot_dialog(page, "store.png")
        try:
            page.get_by_role("dialog").get_by_role(
                "button", name="Claim", exact=True
            ).first.click()
        except Exception:
            # 兜底：直接在页面上找 Claim
            try:
                page.get_by_role("button", name="Claim", exact=True).first.click(
                    timeout=3000
                )
            except Exception as e:
                log(f"商店：确认弹窗点击失败：{e}")
                return False

        # 等待卡片变为 Owned
        try:
            card.get_by_role("button", name="Owned", exact=True).first.wait_for(
                state="visible", timeout=15000
            )
            log("商店：免费塔勒领取成功")
            return True
        except Exception:
            log("警告：未等到 Owned 状态，截取当前领取界面")
            screenshot(page, "store.png")
            return False

    log("商店：Get free 按钮不可用，截取当前领取界面")
    screenshot(page, "store.png")
    return False


# ===================== 主流程 =====================
def main():
    if not ACCOUNT_ID:
        log("错误：未设置 GRIMSOUL_ACCOUNT_ID 环境变量")
        sys.exit(1)

    log("===== 开始执行自动领取 =====")
    ok_daily = False
    ok_store = False

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="en-US", viewport={"width": 1440, "height": 900}
        )
        page = context.new_page()
        try:
            if not login(page):
                log("登录失败，脚本终止")
                screenshot(page, "login_error.png")
                sys.exit(1)

            # 领取函数内部按结果自行截图：
            #   成功 -> 成功弹窗；失败/已领取 -> 当前领取界面
            ok_daily = claim_daily(page)
            ok_store = claim_free_coins(page)
        except Exception as e:
            log(f"执行异常：{e}")
            screenshot(page, "error.png")
        finally:
            browser.close()

    log(f"结果：每日奖励={'成功' if ok_daily else '失败'}，"
        f"免费塔勒={'成功' if ok_store else '失败'}")
    if not (ok_daily and ok_store):
        sys.exit(1)
    log("===== 全部任务完成 =====")


if __name__ == "__main__":
    main()
