#!/usr/bin/env python3
"""
update_device_ca.py
-------------------
自動解析並提取符合 Uni-Shrimp 探頭合約規範的單一伺服器根 CA 公開憑證（Root CA PEM）。

規範依據 (docs/probe-ingest.md & backend/routers/devices.py):
1. 必須為單一 X.509 PEM 憑證（不可為 Bundle/憑證鏈、不可含私鑰）。
2. 字元長度必須 <= 4096 字元。
3. 必須符合正規表示式:
   r"^-----BEGIN CERTIFICATE-----\\s+[A-Za-z0-9+/=\\s]+-----END CERTIFICATE-----$"
4. 必須能由 OpenSSL / Python SSLContext 成功載入驗證。

使用方式:
    # 提取憑證並直接更新設定好的目標檔案
    python3 scripts/update_device_ca.py -i /path/to/new_bundle.crt

    # 提取後同時測試指定網域的 TLS 握手驗證
    python3 scripts/update_device_ca.py -i /path/to/new_bundle.crt -d uni-shrimp.ctyuni.com.vn

    # 更新後自動重啟後端容器
    python3 scripts/update_device_ca.py -i /path/to/new_bundle.crt --restart
"""

import argparse
import os
import re
import shutil
import ssl
import subprocess
import sys
from datetime import datetime
from pathlib import Path


DEFAULT_OUTPUT = Path("/home/elliot/docker/star_ctyuni_com_vn_rootca.crt")
CERT_REGEX = re.compile(r"^-----BEGIN CERTIFICATE-----\s+[A-Za-z0-9+/=\s]+-----END CERTIFICATE-----$")


def get_cert_info(cert_pem: str) -> dict:
    """使用 openssl 指令解析單張 PEM 憑證資訊"""
    info = {"subject": "", "issuer": "", "dates": "", "is_self_signed": False}
    try:
        proc = subprocess.run(
            ["openssl", "x509", "-noout", "-subject", "-issuer", "-dates"],
            input=cert_pem,
            text=True,
            capture_output=True,
            check=True,
        )
        for line in proc.stdout.splitlines():
            if line.startswith("subject="):
                info["subject"] = line.replace("subject=", "").strip()
            elif line.startswith("issuer="):
                info["issuer"] = line.replace("issuer=", "").strip()
            elif line.startswith("notBefore="):
                info["dates"] += line.strip() + " ~ "
            elif line.startswith("notAfter="):
                info["dates"] += line.strip()

        if info["subject"] and info["subject"] == info["issuer"]:
            info["is_self_signed"] = True
    except Exception as e:
        info["subject"] = f"(openssl parse failed: {e})"
    return info


def validate_backend_rules(pem: str) -> None:
    """依據後端 backend/routers/devices.py:51-65 進行相容性檢驗"""
    pem_str = pem.strip()
    if len(pem_str) > 4096:
        raise ValueError(f"憑證長度超過上限 4096 字元 (目前: {len(pem_str)} 字元)")

    if not CERT_REGEX.fullmatch(pem_str):
        raise ValueError("憑證格式不符合單一 PEM 憑證規範 (不可包含憑證鏈或雜質)")

    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.load_verify_locations(cadata=pem_str)
    except Exception as e:
        raise ValueError(f"Python SSLContext 無法載入該憑證: {e}")


def main():
    parser = argparse.ArgumentParser(description="Uni-Shrimp 設備根 CA (Root CA) 憑證解析與更新工具")
    parser.add_argument("-i", "--input", required=True, type=Path, help="來源憑證檔案 (可為單一憑證或 CA Bundle 鏈)")
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT, help=f"輸出目標路徑 (預設: {DEFAULT_OUTPUT})")
    parser.add_argument("-d", "--test-domain", type=str, default="", help="可選：測試 TLS 連線握手的伺服器網域名稱 (例如 uni-shrimp.ctyuni.com.vn)")
    parser.add_argument("-p", "--test-port", type=int, default=443, help="測試 TLS 連線的連接埠 (預設: 443)")
    parser.add_argument("--restart", action="store_true", help="憑證更新後自動執行 docker compose up -d backend")
    parser.add_argument("--no-backup", action="store_true", help="不備份現有目標檔案")

    args = parser.parse_args()

    if not args.input.is_file():
        print(f"[錯誤] 來源檔案不存在: {args.input}", file=sys.stderr)
        sys.exit(1)

    raw_content = args.input.read_text(encoding="utf-8", errors="ignore")
    raw_certs = re.findall(r"-----BEGIN CERTIFICATE-----[\s\S]*?-----END CERTIFICATE-----", raw_content)

    if not raw_certs:
        print(f"[錯誤] 在檔案中未找到任何 PEM 格式憑證: {args.input}", file=sys.stderr)
        sys.exit(1)

    print(f"[*] 來源檔案: {args.input} (共找到 {len(raw_certs)} 張憑證)")
    print("-" * 70)

    selected_cert = None
    cert_info_list = []

    for idx, c in enumerate(raw_certs, 1):
        clean_c = c.strip()
        info = get_cert_info(clean_c)
        cert_info_list.append((idx, clean_c, info))
        tag = "[自簽署根 CA (Root CA)]" if info["is_self_signed"] else "[中間憑證 (Intermediate CA)]"
        print(f"[{idx}] {tag}")
        print(f"    Subject: {info['subject']}")
        print(f"    Issuer:  {info['issuer']}")
        print(f"    Validity: {info['dates']}")
        print(f"    Size:     {len(clean_c)} bytes")

    # 選擇最佳根憑證：
    # 針對 ESP32 (mbedTLS) 等嵌入式設備，憑證鏈越短越穩定。
    # 若 Bundle 中包含交叉簽署（Cross-signed）憑證（如 Sectigo R46 被老舊 USERTrust 簽署），
    # 應優先選擇直接簽發中繼憑證的 Root CA（如 R46），而非深層的交叉簽署老根憑證（如 USERTrust）。
    direct_roots = []
    if len(cert_info_list) >= 2:
        # 第一張通常是 Intermediate CA
        first_issuer = cert_info_list[0][2]["issuer"]
        for item in cert_info_list[1:]:
            if item[2]["subject"] == first_issuer:
                direct_roots.append(item)

    if direct_roots:
        selected_idx, selected_cert, selected_info = direct_roots[0]
        print("-" * 70)
        print(f"[+] 自動選中中繼 CA 的直接根節點 (Direct Root CA): 憑證 [{selected_idx}]")
        print(f"    說明：直接簽發中繼憑證，避免深層交叉簽署鏈 (Cross-signing)，適合 ESP32 連線。")
    else:
        # 若無直接對應，優先選擇自簽署 Root CA，若無則選最頂層憑證
        self_signed = [item for item in cert_info_list if item[2]["is_self_signed"]]
        if self_signed:
            selected_idx, selected_cert, selected_info = self_signed[-1]
            print("-" * 70)
            print(f"[+] 自動選中自簽署 Root CA: 憑證 [{selected_idx}]")
        else:
            selected_idx, selected_cert, selected_info = cert_info_list[-1]
            print("-" * 70)
            print(f"[!] 警告：未找到自簽署 Root CA，選取鏈中最頂層憑證: 憑證 [{selected_idx}]")


    # 執行嚴格檢驗
    print("[*] 正在檢驗是否符合 Uni-Shrimp probe-ingest 規範...")
    try:
        validate_backend_rules(selected_cert)
        print(f"[V] 驗證通過！憑證為單一 PEM，長度 {len(selected_cert.strip())} 字元 (<= 4096)，SSLContext 載入正常。")
    except ValueError as err:
        print(f"[錯誤] 驗證失敗: {err}", file=sys.stderr)
        sys.exit(1)

    # 備份既有檔案
    if args.output.exists() and not args.no_backup:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = args.output.with_suffix(f".crt.bak_{ts}")
        shutil.copy2(args.output, backup_path)
        print(f"[+] 已備份原憑證至: {backup_path}")

    # 寫入目標檔案
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(selected_cert.strip() + "\n", encoding="ascii")
    print(f"[+] 成功寫入單一根 CA 憑證至: {args.output}")

    # 若指定測試網域，進行 TLS 握手測試
    if args.test_domain:
        print("-" * 70)
        print(f"[*] 正在對 {args.test_domain}:{args.test_port} 執行 TLS 握手驗證...")
        try:
            ctx = ssl.create_default_context(cadata=selected_cert.strip() + "\n")
            import socket
            with socket.create_connection((args.test_domain, args.test_port), timeout=5) as sock:
                with ctx.wrap_socket(sock, server_hostname=args.test_domain) as ssock:
                    peer_subj = ssock.getpeercert()["subject"]
                    print(f"[V] TLS 握手驗證成功！對端憑證 Subject: {peer_subj}")
        except Exception as e:
            print(f"[!] TLS 握手測試失敗 (請確認該網域是否指向本機或網路暢通): {e}", file=sys.stderr)

    # 若指定重啟容器
    if args.restart:
        print("-" * 70)
        print("[*] 正在重新啟動後端容器 (docker compose up -d backend)...")
        res = subprocess.run(["docker", "compose", "up", "-d", "backend"])
        if res.returncode == 0:
            print("[V] 後端容器重啟成功！")
        else:
            print("[錯誤] 後端容器重啟失敗，請手動檢查 docker logs。", file=sys.stderr)

    print("-" * 70)
    print("完成！")


if __name__ == "__main__":
    main()
