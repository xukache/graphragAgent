"""MinerU 精准解析 API（路径 B）MVP 完整 pipeline。

流程：
    本地 PDF 加载
      -> 申请上传链接（POST /api/v4/file-urls/batch）
      -> PUT 上传文件到 OSS
      -> 轮询批量结果（GET /api/v4/extract-results/batch/{batch_id}）
      -> 下载 full_zip_url 并解压
      -> 本地落盘存储解析结果

依据 docs/mineru_parsing_spec.md 实现。本地文件解析必须走批量上传接口，
因为单文件 /api/v4/extract/task 仅支持文件 URL，不支持直接上传本地文件。
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


# --------------------------------------------------------------------------- #
# 配置加载
# --------------------------------------------------------------------------- #
@dataclass
class MineruConfig:
    token: str
    api_base: str
    model_version: str
    language: str
    enable_table: bool
    enable_formula: bool
    is_ocr: bool
    poll_interval: int
    poll_timeout: int

    @classmethod
    def from_env(cls) -> "MineruConfig":
        load_dotenv(Path(__file__).resolve().parent / ".env")
        token = os.getenv("MINERU_API_TOKEN", "").strip()
        if not token:
            raise RuntimeError("缺少 MINERU_API_TOKEN，请在 .env 中配置")
        return cls(
            token=token,
            api_base=os.getenv("MINERU_API_BASE", "https://mineru.net/api/v4").strip(),
            model_version=os.getenv("MINERU_MODEL_VERSION", "vlm").strip(),
            language=os.getenv("MINERU_LANGUAGE", "ch").strip(),
            enable_table=os.getenv("MINERU_ENABLE_TABLE", "true").lower() == "true",
            enable_formula=os.getenv("MINERU_ENABLE_FORMULA", "true").lower() == "true",
            is_ocr=os.getenv("MINERU_IS_OCR", "false").lower() == "true",
            poll_interval=int(os.getenv("MINERU_POLL_INTERVAL", "5")),
            poll_timeout=int(os.getenv("MINERU_POLL_TIMEOUT", "600")),
        )

    @property
    def auth_header(self) -> dict[str, str]:
        # 注意：Bearer 后必须有空格，漏写返回 A0202
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
            "Accept": "*/*",
        }


# --------------------------------------------------------------------------- #
# MinerU 客户端
# --------------------------------------------------------------------------- #
class MineruClient:
    def __init__(self, config: MineruConfig) -> None:
        self.config = config

    def apply_upload_url(self, file_name: str, data_id: str | None = None) -> tuple[str, str]:
        """申请本地文件上传链接，返回 (batch_id, upload_url)。"""
        url = f"{self.config.api_base}/file-urls/batch"
        file_entry: dict[str, Any] = {"name": file_name}
        if data_id:
            file_entry["data_id"] = data_id

        payload = {
            "enable_formula": self.config.enable_formula,
            "enable_table": self.config.enable_table,
            "language": self.config.language,
            "model_version": self.config.model_version,
            "files": [file_entry],
        }
        # is_ocr 是 file 级参数
        file_entry["is_ocr"] = self.config.is_ocr

        print(f"[1/5] 申请上传链接 -> {url}")
        resp = requests.post(url, headers=self.config.auth_header, json=payload, timeout=60)
        resp.raise_for_status()
        result = resp.json()
        if result.get("code") != 0:
            raise RuntimeError(f"申请上传链接失败: code={result.get('code')} msg={result.get('msg')}")

        data = result["data"]
        batch_id = data["batch_id"]
        file_urls = data["file_urls"]
        if not file_urls:
            raise RuntimeError("接口未返回上传链接 file_urls")
        print(f"      batch_id={batch_id}")
        return batch_id, file_urls[0]

    def upload_file(self, upload_url: str, file_path: Path) -> None:
        """PUT 上传本地文件到 OSS，无须设置 Content-Type。"""
        print(f"[2/5] 上传文件 {file_path.name} -> OSS")
        with file_path.open("rb") as f:
            # 不要带 Authorization / Content-Type，否则 OSS 签名校验会失败
            resp = requests.put(upload_url, data=f, timeout=300)
        if resp.status_code != 200:
            raise RuntimeError(f"文件上传失败: status={resp.status_code} body={resp.text[:200]}")
        print("      上传成功")

    def poll_batch_result(self, batch_id: str) -> dict[str, Any]:
        """轮询批量任务结果，直到 done / failed / 超时。"""
        url = f"{self.config.api_base}/extract-results/batch/{batch_id}"
        print(f"[3/5] 轮询解析结果 -> {url}")
        deadline = time.time() + self.config.poll_timeout

        while time.time() < deadline:
            resp = requests.get(url, headers=self.config.auth_header, timeout=60)
            resp.raise_for_status()
            result = resp.json()
            if result.get("code") != 0:
                raise RuntimeError(f"查询结果失败: code={result.get('code')} msg={result.get('msg')}")

            extract_results = result["data"].get("extract_result", [])
            if not extract_results:
                print("      暂无结果，等待中...")
                time.sleep(self.config.poll_interval)
                continue

            item = extract_results[0]
            state = item.get("state")
            if state == "done":
                print(f"      解析完成: {item.get('file_name')}")
                return item
            if state == "failed":
                raise RuntimeError(f"解析失败: {item.get('err_msg')}")

            progress = item.get("extract_progress", {})
            extracted = progress.get("extracted_pages", "?")
            total = progress.get("total_pages", "?")
            print(f"      state={state} 进度={extracted}/{total}，{self.config.poll_interval}s 后重试")
            time.sleep(self.config.poll_interval)

        raise TimeoutError(f"轮询超时（{self.config.poll_timeout}s），任务未完成")

    @staticmethod
    def _download_zip(zip_url: str, max_retries: int = 4) -> bytes:
        """下载结果 zip，带重试。

        MinerU 结果 CDN（*.openxlab.org.cn）为国内域名，若本机走了代理可能
        出现 SSL EOF，或 SOCKS 代理触发 "Missing dependencies for SOCKS support"。
        因此重试时回退到「绕过代理」直连。

        注意：requests 的 `proxies=` 参数只覆盖 http/https，不覆盖环境变量里的
        SOCKS `all_proxy`。要彻底绕过，必须在进程环境层面清掉代理变量，并对
        session 显式设置 trust_env=False。
        """
        import os as _os

        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            use_proxy = attempt == 1
            mode = "系统代理" if use_proxy else "绕过代理直连"

            # 后续尝试：临时清空代理环境变量 + trust_env=False，彻底绕过 SOCKS
            saved_env: dict[str, str] = {}
            proxy_keys = ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy",
                          "HTTPS_PROXY", "https_proxy")
            try:
                if not use_proxy:
                    for k in proxy_keys:
                        if k in _os.environ:
                            saved_env[k] = _os.environ.pop(k)

                session = requests.Session()
                if not use_proxy:
                    session.trust_env = False  # 不读环境里的代理配置
                    session.proxies = {}
                resp = session.get(zip_url, timeout=300)
                resp.raise_for_status()
                if attempt > 1:
                    print(f"      （第 {attempt} 次尝试，{mode} 成功）")
                return resp.content
            except requests.exceptions.RequestException as exc:  # noqa: PERF203
                last_exc = exc
                print(f"      下载失败（第 {attempt}/{max_retries} 次，{mode}）: {type(exc).__name__}")
                time.sleep(2 * attempt)
            finally:
                # 恢复环境变量，避免影响进程内其它请求
                for k, v in saved_env.items():
                    _os.environ[k] = v
        raise RuntimeError(f"结果下载失败，已重试 {max_retries} 次") from last_exc

    @classmethod
    def download_and_extract(cls, zip_url: str, output_dir: Path) -> list[str]:
        """下载 full_zip_url 并解压到 output_dir。"""
        print(f"[4/5] 下载并解压结果 -> {output_dir}")
        content = cls._download_zip(zip_url)

        output_dir.mkdir(parents=True, exist_ok=True)
        # 保留一份原始 zip，便于复查
        zip_path = output_dir / "result.zip"
        zip_path.write_bytes(content)

        names: list[str] = []
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            zf.extractall(output_dir)
            names = zf.namelist()
        print(f"      解压完成，共 {len(names)} 个条目")
        return names


# --------------------------------------------------------------------------- #
# 解析结果概览
# --------------------------------------------------------------------------- #
def summarize_output(output_dir: Path, file_names: list[str]) -> None:
    """打印解析输出文件清单，并对 content_list.json 做块类型统计。"""
    print("[5/5] 解析结果概览")
    print("      生成文件:")
    for name in sorted(file_names):
        print(f"        - {name}")

    # 查找 content_list.json 做块类型统计
    content_list_files = list(output_dir.rglob("*content_list.json"))
    if content_list_files:
        cl_path = content_list_files[0]
        try:
            blocks = json.loads(cl_path.read_text(encoding="utf-8"))
            type_count: dict[str, int] = {}
            for block in blocks:
                btype = block.get("type", "unknown")
                type_count[btype] = type_count.get(btype, 0) + 1
            print(f"\n      content_list.json 块类型统计 ({cl_path.name}):")
            for btype, count in sorted(type_count.items()):
                print(f"        {btype}: {count}")
        except Exception as exc:  # noqa: BLE001
            print(f"      解析 content_list.json 失败: {exc}")

    # 打印 full.md 前若干行
    md_files = list(output_dir.rglob("full.md"))
    if md_files:
        md_text = md_files[0].read_text(encoding="utf-8")
        preview = "\n".join(md_text.splitlines()[:15])
        print(f"\n      full.md 预览（前 15 行）:\n")
        for line in preview.splitlines():
            print(f"        | {line}")


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def run_pipeline(pdf_path: Path, output_dir: Path) -> None:
    if not pdf_path.exists():
        raise FileNotFoundError(f"待解析文件不存在: {pdf_path}")

    print("=" * 70)
    print("MinerU 精准解析 API（路径 B）MVP Pipeline")
    print(f"输入文件: {pdf_path}")
    print(f"输出目录: {output_dir}")
    print("=" * 70)

    config = MineruConfig.from_env()
    print(
        f"配置: model_version={config.model_version} language={config.language} "
        f"enable_table={config.enable_table} enable_formula={config.enable_formula} "
        f"is_ocr={config.is_ocr}"
    )

    client = MineruClient(config)

    batch_id, upload_url = client.apply_upload_url(pdf_path.name, data_id="mineru_mvp_001")
    client.upload_file(upload_url, pdf_path)
    result_item = client.poll_batch_result(batch_id)

    zip_url = result_item["full_zip_url"]
    file_names = client.download_and_extract(zip_url, output_dir)

    # 保存任务元数据
    meta = {
        "batch_id": batch_id,
        "file_name": result_item.get("file_name"),
        "data_id": result_item.get("data_id"),
        "full_zip_url": zip_url,
        "state": result_item.get("state"),
    }
    (output_dir / "task_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    summarize_output(output_dir, file_names)

    print("\n" + "=" * 70)
    print("Pipeline 执行完成 ✅")
    print(f"结果已存储于: {output_dir}")
    print("=" * 70)


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent
    default_pdf = base_dir / "sample.pdf"

    pdf_arg = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else default_pdf
    out_dir = base_dir / "output"

    run_pipeline(pdf_arg, out_dir)
