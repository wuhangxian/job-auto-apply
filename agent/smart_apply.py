"""智能投递引擎 v2：AI搜索官网 → 验证URL可访问 → Playwright打开 → 找入口 → 填表。"""

from __future__ import annotations

import json
import time
import base64
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote_plus

import requests
from playwright.sync_api import sync_playwright, Page


@dataclass
class ApplyStep:
    step: int
    action: str
    detail: str
    screenshot: str = ""
    url: str = ""
    status: str = ""


@dataclass
class SmartApplyResult:
    steps: list[ApplyStep] = field(default_factory=list)
    final_screenshot: str = ""
    page_title: str = ""
    page_url: str = ""
    form_found: bool = False
    fields_detected: int = 0
    fields_filled: int = 0
    error: str = ""
    answers: list[dict] = field(default_factory=list)


def _verify_url(url: str, timeout: int = 5) -> bool:
    """检查 URL 是否可访问。"""
    try:
        r = requests.get(url, timeout=timeout, allow_redirects=True, verify=False,
                         headers={'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'})
        return r.status_code == 200
    except Exception:
        return False


def _search_baidu(company: str) -> list[str]:
    """用百度搜索校招网址，返回候选 URL 列表。"""
    query = f'{company} 校招 网申 site:mokahr.com OR site:zhaopin.com OR site:51job.com OR site:zhipin.com OR site:hotjob.cn'
    try:
        r = requests.get('https://www.baidu.com/s', params={'wd': query}, timeout=10,
                         headers={'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'})
        import re
        urls = re.findall(r'href="(https?://[^"]+)"', r.text)
        relevant = [u for u in urls if any(kw in u.lower() for kw in ['mokahr', 'zhaopin', '51job', 'zhipin', 'hotjob', 'campus', 'job'])]
        return relevant[:5]
    except Exception:
        return []


def _search_via_ai(company: str, title: str, ai_chat) -> list[str]:
    """让 AI 搜索该公司校招网申入口，返回多个候选 URL。"""
    system = """你是一个求职助手。根据公司名和岗位名，找到该公司官方校招网申系统的入口 URL。

规则：
1. 优先返回官方校招网申系统的直接链接
2. 常见网申系统域名包括：mokahr.com, zhaopin.com, beisen.com, 51job.com, zhipin.com, hotjob.cn 等
3. 如果没有找到网申系统，返回公司校招官网首页
4. 返回 JSON 数组，包含多个候选 URL"""

    user = f"""公司：{company}
岗位：{title}

请搜索该公司的校招网申入口，返回 3-5 个候选 URL。"""

    try:
        text = ai_chat(system, user)
        if '```json' in text:
            text = text.split('```json')[1].split('```')[0]
        elif '```' in text:
            text = text.split('```')[1].split('```')[0]
        urls = json.loads(text.strip())
        if isinstance(urls, list):
            return [u for u in urls if isinstance(u, str) and u.startswith('http')]
    except Exception:
        pass
    return []


def smart_apply(
    company: str,
    title: str,
    job_url: str,
    ai_chat,
    answers: list[dict],
    profile_data: dict,
    headless: bool = True,
) -> SmartApplyResult:
    """完整流程：搜索官网 → 验证URL → 打开 → 找入口 → 填表 → 截图。"""

    result = SmartApplyResult(answers=answers)
    step = 0

    try:
        # Step 1: AI 搜索候选 URL
        step += 1
        ai_urls = _search_via_ai(company, title, ai_chat)
        result.steps.append(ApplyStep(
            step=step, action='ai_search',
            detail=f'AI 找到 {len(ai_urls)} 个候选: {json.dumps(ai_urls, ensure_ascii=False)[:200]}',
            status='ok' if ai_urls else 'skip',
        ))

        # Step 2: 验证每个 URL 是否可访问
        step += 1
        valid_url = ''
        for url in ai_urls:
            if _verify_url(url):
                valid_url = url
                break
        result.steps.append(ApplyStep(
            step=step, action='verify',
            detail=f'验证通过: {valid_url or "全部不可访问"}',
            url=valid_url,
            status='ok' if valid_url else 'skip',
        ))

        # Step 3: 如果 AI URL 全不可用，百度搜索
        if not valid_url:
            step += 1
            baidu_urls = _search_baidu(company)
            result.steps.append(ApplyStep(
                step=step, action='baidu_search',
                detail=f'百度找到 {len(baidu_urls)} 个候选',
                status='ok' if baidu_urls else 'skip',
            ))
            for url in baidu_urls:
                if _verify_url(url):
                    valid_url = url
                    break
            step += 1
            result.steps.append(ApplyStep(
                step=step, action='verify_baidu',
                detail=f'百度验证通过: {valid_url or "全部不可访问"}',
                url=valid_url,
                status='ok' if valid_url else 'skip',
            ))

        # Step 4: 如果还是没找到，用原始链接
        if not valid_url:
            valid_url = job_url
            step += 1
            result.steps.append(ApplyStep(
                step=step, action='fallback',
                detail=f'使用原始链接: {valid_url}',
                url=valid_url,
                status='ok',
            ))

        # Step 5: Playwright 打开页面
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            page = browser.new_page()
            step += 1
            try:
                page.goto(valid_url, wait_until='domcontentloaded', timeout=30000)
                time.sleep(3)
            except Exception as e:
                step += 1
                result.steps.append(ApplyStep(
                    step=step, action='open_error',
                    detail=f'打开失败: {str(e)[:100]}',
                    status='error',
                ))
                browser.close()
                return result

            result.page_title = page.title()
            result.page_url = page.url
            ss = page.screenshot()
            result.steps.append(ApplyStep(
                step=step, action='open',
                detail=f'页面: {result.page_title}',
                screenshot=base64.b64encode(ss).decode(),
                url=result.page_url,
                status='ok',
            ))

            # Step 6: 检测表单
            step += 1
            inputs = page.query_selector_all('input, textarea, select')
            visible_inputs = []
            for inp in inputs:
                try:
                    if inp.is_visible() and inp.get_attribute('type') not in ('hidden', 'submit', 'button', 'reset', 'image'):
                        visible_inputs.append(inp)
                except Exception:
                    continue

            result.fields_detected = len(visible_inputs)
            result.form_found = len(visible_inputs) > 0
            ss = page.screenshot()
            field_names = [inp.get_attribute('name') or inp.get_attribute('id') or inp.get_attribute('placeholder') or 'unknown' for inp in visible_inputs[:15]]
            result.steps.append(ApplyStep(
                step=step, action='detect_form',
                detail=f'检测到 {len(visible_inputs)} 个表单字段: {json.dumps(field_names, ensure_ascii=False)[:200]}',
                screenshot=base64.b64encode(ss).decode(),
                status='ok' if visible_inputs else 'skip',
            ))

            # Step 7: 如果没表单，尝试点击入口按钮
            if not result.form_found:
                # Try multiple strategies to find entry points
                click_keywords = ['投递', '网申', '注册', '登录', '投简历', '申请职位', '我要投递', 'campus', 'apply', 'register', '立即投递', '进入', '招聘', '职位']
                clicked = False

                # Strategy 1: Click text buttons
                for kw in click_keywords:
                    try:
                        btn = page.get_by_text(kw, exact=False).first
                        if btn and btn.is_visible():
                            step += 1
                            result.steps.append(ApplyStep(
                                step=step, action='click_entry',
                                detail=f'点击文字: {kw}',
                                status='ok',
                            ))
                            btn.click()
                            time.sleep(3)
                            result.page_title = page.title()
                            result.page_url = page.url
                            step += 1
                            ss = page.screenshot()
                            result.steps.append(ApplyStep(
                                step=step, action='after_click',
                                detail=f'跳转到: {result.page_title} ({result.page_url})',
                                screenshot=base64.b64encode(ss).decode(),
                                url=result.page_url,
                                status='ok',
                            ))
                            inputs2 = page.query_selector_all('input, textarea, select')
                            visible_inputs2 = [inp for inp in inputs2 if inp.is_visible() and inp.get_attribute('type') not in ('hidden', 'submit', 'button', 'reset', 'image')]
                            result.fields_detected = len(visible_inputs2)
                            result.form_found = len(visible_inputs2) > 0
                            visible_inputs = visible_inputs2
                            step += 1
                            ss2 = page.screenshot()
                            result.steps.append(ApplyStep(
                                step=step, action='detect_form_2',
                                detail=f'第二次检测: {len(visible_inputs2)} 个表单字段',
                                screenshot=base64.b64encode(ss2).decode(),
                                status='ok' if visible_inputs2 else 'skip',
                            ))
                            clicked = True
                            break
                    except Exception:
                        continue

                # Strategy 2: Follow links with job-related hrefs
                if not clicked:
                    try:
                        all_links = page.query_selector_all('a')
                        for link in all_links:
                            href = link.get_attribute('href') or ''
                            if any(kw in href.lower() for kw in ['job', 'apply', 'post', 'about', 'position', 'campus', 'recruit', 'resume']):
                                if link.is_visible():
                                    step += 1
                                    link_text = link.inner_text()[:30] or 'image link'
                                    result.steps.append(ApplyStep(
                                        step=step, action='click_link',
                                        detail=f'点击链接: {link_text} -> {href}',
                                        status='ok',
                                    ))
                                    link.click()
                                    time.sleep(3)
                                    result.page_title = page.title()
                                    result.page_url = page.url
                                    step += 1
                                    ss = page.screenshot()
                                    result.steps.append(ApplyStep(
                                        step=step, action='after_link',
                                        detail=f'跳转到: {result.page_title} ({result.page_url})',
                                        screenshot=base64.b64encode(ss).decode(),
                                        url=result.page_url,
                                        status='ok',
                                    ))
                                    # Re-detect form
                                    inputs2 = page.query_selector_all('input, textarea, select')
                                    visible_inputs2 = [inp for inp in inputs2 if inp.is_visible() and inp.get_attribute('type') not in ('hidden', 'submit', 'button', 'reset', 'image')]
                                    result.fields_detected = len(visible_inputs2)
                                    result.form_found = len(visible_inputs2) > 0
                                    visible_inputs = visible_inputs2
                                    step += 1
                                    ss2 = page.screenshot()
                                    result.steps.append(ApplyStep(
                                        step=step, action='detect_form_2',
                                        detail=f'第二次检测: {len(visible_inputs2)} 个表单字段',
                                        screenshot=base64.b64encode(ss2).decode(),
                                        status='ok' if visible_inputs2 else 'skip',
                                    ))
                                    clicked = True
                                    break
                    except Exception:
                        pass

                # Strategy 3: Click images
                if not clicked:
                    try:
                        imgs = page.query_selector_all('img')
                        for img in imgs:
                            if img.is_visible():
                                parent = img.evaluate('el => el.parentElement ? el.parentElement.tagName + (el.parentElement.href ? " -> "+el.parentElement.href : "") : "none"')
                                if 'A' in parent and 'href' in parent:
                                    step += 1
                                    result.steps.append(ApplyStep(
                                        step=step, action='click_image',
                                        detail=f'点击图片: parent={parent[:80]}',
                                        status='ok',
                                    ))
                                    img.click()
                                    time.sleep(3)
                                    result.page_title = page.title()
                                    result.page_url = page.url
                                    step += 1
                                    ss = page.screenshot()
                                    result.steps.append(ApplyStep(
                                        step=step, action='after_image',
                                        detail=f'跳转到: {result.page_title} ({result.page_url})',
                                        screenshot=base64.b64encode(ss).decode(),
                                        url=result.page_url,
                                        status='ok',
                                    ))
                                    inputs2 = page.query_selector_all('input, textarea, select')
                                    visible_inputs2 = [inp for inp in inputs2 if inp.is_visible() and inp.get_attribute('type') not in ('hidden', 'submit', 'button', 'reset', 'image')]
                                    result.fields_detected = len(visible_inputs2)
                                    result.form_found = len(visible_inputs2) > 0
                                    visible_inputs = visible_inputs2
                                    step += 1
                                    ss2 = page.screenshot()
                                    result.steps.append(ApplyStep(
                                        step=step, action='detect_form_2',
                                        detail=f'第二次检测: {len(visible_inputs2)} 个表单字段',
                                        screenshot=base64.b64encode(ss2).decode(),
                                        status='ok' if visible_inputs2 else 'skip',
                                    ))
                                    clicked = True
                                    break
                    except Exception:
                        pass

                if not clicked:
                    step += 1
                    result.steps.append(ApplyStep(
                        step=step, action='no_entry',
                        detail='未找到投递/注册入口',
                        status='skip',
                    ))

            # Step 8+: 逐字段填写
            answer_map = {}
            for a in answers:
                answer_map[a.get('field_name', '').lower()] = a.get('value', '')

            for inp in visible_inputs:
                try:
                    field_name = (inp.get_attribute('name') or inp.get_attribute('id') or inp.get_attribute('placeholder') or '').lower()
                    field_type = inp.get_attribute('type') or 'text'
                    tag = inp.evaluate('el => el.tagName.toLowerCase()')
                except Exception:
                    continue

                matched_value = ''
                matched_key = ''
                for key, val in answer_map.items():
                    if not key or not val:
                        continue
                    if key in field_name or field_name in key:
                        matched_value = val
                        matched_key = key
                        break

                if not matched_value:
                    generic_map = {
                        'name': profile_data.get('name', ''),
                        'phone': profile_data.get('phone', ''),
                        'mobile': profile_data.get('phone', ''),
                        'tel': profile_data.get('phone', ''),
                        'email': profile_data.get('email', ''),
                        'school': profile_data.get('school', ''),
                        'university': profile_data.get('school', ''),
                        'major': profile_data.get('major', ''),
                    }
                    for gkey, gval in generic_map.items():
                        if gkey in field_name and gval:
                            matched_value = gval
                            matched_key = f'generic:{gkey}'
                            break

                step += 1
                if not matched_value:
                    result.steps.append(ApplyStep(
                        step=step, action='skip_field',
                        detail=f'跳过字段: {field_name} (无匹配数据)',
                        status='skip',
                    ))
                    continue

                try:
                    if tag == 'select':
                        inp.select_option(label=matched_value)
                    elif field_type == 'checkbox':
                        if matched_value in ('是', 'yes', 'true', '1'):
                            inp.check()
                    elif field_type == 'radio':
                        inp.check()
                    else:
                        inp.fill('')
                        inp.type(matched_value, delay=30)

                    time.sleep(0.5)
                    ss = page.screenshot()
                    result.steps.append(ApplyStep(
                        step=step, action='fill_field',
                        detail=f'填入 {field_name} = {matched_value[:60]} (来源: {matched_key})',
                        screenshot=base64.b64encode(ss).decode(),
                        status='ok',
                    ))
                    result.fields_filled += 1
                except Exception as e:
                    result.steps.append(ApplyStep(
                        step=step, action='error_field',
                        detail=f'填写失败 {field_name}: {str(e)[:80]}',
                        status='error',
                    ))

            # 最终截图
            step += 1
            ss = page.screenshot(full_page=True)
            result.final_screenshot = base64.b64encode(ss).decode()
            result.steps.append(ApplyStep(
                step=step, action='final',
                detail=f'完成: 检测到 {result.fields_detected} 个字段, 填写 {result.fields_filled} 个',
                screenshot=result.final_screenshot,
                status='ok',
            ))
            browser.close()

    except Exception as e:
        result.error = str(e)
        result.steps.append(ApplyStep(
            step=step + 1, action='error',
            detail=f'系统错误: {str(e)[:150]}',
            status='error',
        ))

    return result
