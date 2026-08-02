"""信息源采集器：腾讯文档 / Boss 直聘 / 猎聘 / 通用网页。"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Callable

import requests


@dataclass(frozen=True)
class CollectedJob:
    source: str
    company: str
    title: str
    url: str
    location: str = ""
    salary: str = ""
    jd: str = ""


def collect_tencent_docs(
    token: str,
    file_ids: list[str],
    tables: list[str] | None = None,
    progress: Callable | None = None,
) -> list[CollectedJob]:
    """从腾讯文档 SmartSheet 采集岗位。"""

    jobs: list[CollectedJob] = []
    mcp_url = "https://docs.qq.com/openapi/mcp"
    headers = {
        "Authorization": token,
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    for file_id in file_ids:
        tables_result = _mcp_call(mcp_url, headers, "smartsheet.list_tables", {"file_id": file_id})
        sheets = tables_result.get("sheets", [])

        for sheet in sheets:
            if not sheet.get("is_visible", True):
                continue
            if tables and sheet.get("sheet_id") not in tables and sheet.get("title") not in tables:
                continue

            offset = 0
            while True:
                result = _mcp_call(mcp_url, headers, "smartsheet.list_records", {
                    "file_id": file_id,
                    "sheet_id": sheet["sheet_id"],
                    "offset": offset,
                    "limit": 100,
                })
                records = result.get("records", [])
                for record in records:
                    job = _parse_tencent_record(record, sheet.get("title", ""))
                    if job:
                        jobs.append(job)

                if progress:
                    progress(len(jobs))

                if not result.get("has_more", False):
                    break
                next_offset = result.get("next")
                if next_offset is None or str(next_offset) <= str(offset):
                    break
                try:
                    offset = int(next_offset)
                except (TypeError, ValueError):
                    offset += len(records)

    return jobs


def _mcp_call(url: str, headers: dict, tool: str, arguments: dict) -> dict:
    """调用腾讯文档 MCP 工具。"""

    init_body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "job-agent", "version": "1.0.0"},
        },
    }
    response = requests.post(url, json=init_body, headers=headers, timeout=30, allow_redirects=False, verify=True)
    if response.status_code != 200:
        raise RuntimeError(f"腾讯文档 MCP 初始化失败: HTTP {response.status_code}")
    init_result = response.json().get("result", {})
    negotiated = init_result.get("protocolVersion", "2025-03-26")
    session_id = init_result.get("sessionId")

    tool_headers = dict(headers)
    tool_headers["MCP-Protocol-Version"] = negotiated
    if session_id:
        tool_headers["Mcp-Session-Id"] = session_id

    tool_body = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }
    response = requests.post(url, json=tool_body, headers=tool_headers, timeout=30, allow_redirects=False, verify=True)
    if response.status_code != 200:
        raise RuntimeError(f"腾讯文档 MCP 调用失败: HTTP {response.status_code}")

    payload = response.json().get("result", {})
    structured = payload.get("structuredContent")
    if isinstance(structured, dict) and structured:
        return structured
    content = payload.get("content", [])
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            return json.loads(item.get("text", "{}"))
    return {}


def _parse_tencent_record(record: dict, table_title: str) -> CollectedJob | None:
    """解析腾讯文档 SmartSheet 记录为岗位。"""

    field_values = record.get("field_values", [])
    if not isinstance(field_values, list):
        return None

    field_map = {}
    for entry in field_values:
        if not isinstance(entry, dict):
            continue
        name = entry.get("field", "")
        value = _convert_field_value(entry)
        if name and value and name not in field_map:
            field_map[name] = value

    company = _pick(field_map, ["招聘企业", "企业名称", "公司"])
    title = _pick(field_map, ["招聘岗位", "岗位", "职位", "岗位名称"])
    url = _pick(field_map, ["投递链接", "申请链接", "网申链接"])

    if not company or not title or not url:
        return None

    return CollectedJob(
        source=f"腾讯文档/{table_title}",
        company=company,
        title=title,
        url=url,
        location=_pick(field_map, ["工作地点", "地点", "城市"]),
        salary=_pick(field_map, ["薪资", "报酬"]),
        jd=_pick(field_map, ["岗位描述", "职位描述", "备注"]),
    )


def _convert_field_value(entry: dict) -> str:
    if "text_value" in entry:
        items = entry["text_value"].get("items", [])
        return " ".join(i.get("text", "") for i in items if isinstance(i, dict) and i.get("text"))
    if "url_value" in entry:
        for i in entry["url_value"].get("items", []):
            if isinstance(i, dict) and i.get("link"):
                return i["link"]
    if "option_value" in entry:
        items = entry["option_value"].get("items", [])
        return "、".join(i.get("text", "") for i in items if isinstance(i, dict) and i.get("text"))
    if "number_value" in entry:
        return str(entry["number_value"])
    if "string_value" in entry:
        return str(entry["string_value"])
    if "bool_value" in entry:
        return "是" if entry["bool_value"] else "否"
    return ""


def _pick(field_map: dict, names: list[str]) -> str:
    for name in names:
        if name in field_map and field_map[name]:
            return field_map[name]
    return ""


def collect_boss(
    token: str,
    keywords: list[str],
    cities: list[str],
    max_results: int = 50,
    progress: Callable | None = None,
) -> list[CollectedJob]:
    """从 Boss 直聘搜索岗位。"""

    jobs: list[CollectedJob] = []
    base_url = "https://www.zhipin.com/wapi/zpgeek/search/joblist.json"

    city_map = {
        "北京": "101010100", "上海": "101020100", "深圳": "101280100",
        "广州": "101280101", "杭州": "101210100", "南京": "101190100",
        "合肥": "101220101", "成都": "101270100", "武汉": "101200100",
        "苏州": "101190400", "西安": "101110100",
    }

    for keyword in keywords:
        for city in cities:
            city_code = city_map.get(city, "")
            if not city_code:
                continue

            page = 1
            while len(jobs) < max_results and page <= 5:
                params = {
                    "scene": "1",
                    "query": keyword,
                    "city": city_code,
                    "page": page,
                    "pageSize": 30,
                }
                headers = {
                    "Cookie": f"wt2={token};",
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                    "Referer": "https://www.zhipin.com/",
                }
                try:
                    response = requests.get(base_url, params=params, headers=headers, timeout=15)
                    data = response.json()
                    if data.get("code") != 0:
                        break
                    job_list = data.get("zpData", {}).get("jobList", [])
                    if not job_list:
                        break

                    for item in job_list:
                        jobs.append(CollectedJob(
                            source="Boss直聘",
                            company=item.get("brandName", ""),
                            title=item.get("jobName", ""),
                            url=f"https://www.zhipin.com/job_detail/{item.get('encryptId', '')}.html",
                            location=item.get("cityName", ""),
                            salary=item.get("salary", ""),
                            jd=item.get("postLabel", ""),
                        ))

                    if progress:
                        progress(len(jobs))
                except Exception:
                    break

                page += 1
                time.sleep(2)

            if len(jobs) >= max_results:
                break
        if len(jobs) >= max_results:
            break

    return jobs[:max_results]


def collect_liepin(
    cookie: str,
    keywords: list[str],
    cities: list[str],
    max_results: int = 30,
    progress: Callable | None = None,
) -> list[CollectedJob]:
    """从猎聘搜索岗位。"""

    jobs: list[CollectedJob] = []
    base_url = "https://api-c.liepin.com/api/com.liepin.search-front.search.pc-search-job"

    city_map = {
        "北京": "010", "上海": "020", "深圳": "050", "广州": "050020",
        "杭州": "070", "南京": "060", "合肥": "150",
    }

    for keyword in keywords:
        for city in cities:
            city_code = city_map.get(city, "")
            payload = {
                "key": keyword,
                "city": city_code,
                "currentPage": 0,
                "pageSize": 30,
            }
            headers = {
                "Cookie": cookie,
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
                "Content-Type": "application/json",
            }
            try:
                response = requests.post(base_url, json=payload, headers=headers, timeout=15)
                data = response.json()
                job_list = data.get("data", {}).get("list", [])

                for item in job_list:
                    job_id = item.get("jobId", "")
                    jobs.append(CollectedJob(
                        source="猎聘",
                        company=item.get("companyName", ""),
                        title=item.get("jobTitle", ""),
                        url=f"https://www.liepin.com/job/{job_id}.shtml",
                        location=item.get("cityName", ""),
                        salary=item.get("salary", ""),
                        jd=item.get("jobDescription", ""),
                    ))

                if progress:
                    progress(len(jobs))
            except Exception:
                continue

            time.sleep(2)

            if len(jobs) >= max_results:
                break
        if len(jobs) >= max_results:
            break

    return jobs[:max_results]


def collect_web(
    keywords: list[str],
    max_results: int = 30,
    progress: Callable | None = None,
) -> list[CollectedJob]:
    """通用网页采集：通过搜索引擎找招聘信息。"""

    jobs: list[CollectedJob] = []

    for keyword in keywords:
        search_url = "https://www.google.com/search"
        params = {
            "q": f"{keyword} 校招 2027",
            "num": 10,
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        }
        try:
            response = requests.get(search_url, params=params, headers=headers, timeout=15)
            # 简单提取搜索结果中的 URL
            urls = re.findall(r'href="(https?://[^"&]+(?:zhipin|51job|liepin|jobs)[^"]*)"', response.text)
            for url in urls[:max_results]:
                jobs.append(CollectedJob(
                    source="网页搜索",
                    company="",
                    title=keyword,
                    url=url,
                    jd="",
                ))
                if progress:
                    progress(len(jobs))
                if len(jobs) >= max_results:
                    break
        except Exception:
            continue

        if len(jobs) >= max_results:
            break

    return jobs[:max_results]
