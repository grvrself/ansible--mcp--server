"""
AnsibleRunner — 通过 paramiko SSH 连接到 Ubuntu Ansible 控制节点，
远程执行 ansible 命令并返回结果。
"""

from __future__ import annotations

import logging
import uuid
import os
import shlex
from typing import Optional

import paramiko

logger = logging.getLogger(__name__)


class AnsibleRunner:
    """管理与 Ubuntu Ansible 控制节点的 SSH 连接，并提供命令执行能力。"""

    def __init__(self, config: dict):
        ctrl = config["ansible_controller"]
        self._host: str = ctrl["host"]
        self._port: int = ctrl.get("port", 22)
        self._user: str = ctrl["user"]
        self._password: str = ctrl.get("password", "")
        self._timeout: int = ctrl.get("timeout", 10)

        ansible_cfg = config.get("ansible", {})
        self._inventory_path: str = ansible_cfg.get(
            "inventory_path", "~/ansible/inventory/hosts"
        )
        self._command_timeout: int = ansible_cfg.get("command_timeout", 120)
        self._become: bool = ansible_cfg.get("become", True)
        self._become_user: str = ansible_cfg.get("become_user", "root")

        self._client: Optional[paramiko.SSHClient] = None

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """建立 SSH 连接到 Ubuntu 控制节点。"""
        if self._client is not None:
            return

        logger.info("SSH 连接到 %s@%s:%d", self._user, self._host, self._port)
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            client.connect(
                hostname=self._host,
                port=self._port,
                username=self._user,
                password=self._password,
                timeout=self._timeout,
                allow_agent=False,
                look_for_keys=False,
            )
        except Exception:
            logger.exception("SSH 连接失败")
            raise

        self._client = client
        logger.info("SSH 连接成功")

    def close(self) -> None:
        """关闭 SSH 连接。"""
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    def _ensure_connected(self) -> None:
        """确保连接可用，断开则自动重连。"""
        if self._client is None:
            self.connect()
            return
        transport = self._client.get_transport()
        if transport is None or not transport.is_active():
            self._client = None
            self.connect()

    # ------------------------------------------------------------------
    # 命令执行
    # ------------------------------------------------------------------

    def execute(
        self, command: str, timeout: Optional[int] = None
    ) -> tuple[int, str, str]:
        """在 Ubuntu 上执行 shell 命令。

        Returns:
            (exit_code, stdout, stderr)
        """
        self._ensure_connected()
        timeout = timeout or self._command_timeout
        logger.info("执行命令: %s", command[:200])

        stdin, stdout, stderr = self._client.exec_command(
            command, timeout=timeout
        )
        exit_code = stdout.channel.recv_exit_status()
        stdout_text = stdout.read().decode("utf-8", errors="replace").strip()
        stderr_text = stderr.read().decode("utf-8", errors="replace").strip()

        logger.info(
            "exit=%d stdout=%d stderr=%d bytes",
            exit_code,
            len(stdout_text),
            len(stderr_text),
        )
        return exit_code, stdout_text, stderr_text

    def upload_content(self, content: str, remote_path: str) -> None:
        """通过 SFTP 上传文本内容到远程文件。"""
        self._ensure_connected()
        sftp = self._client.open_sftp()
        try:
            with sftp.file(remote_path, "w") as f:
                f.write(content)
        finally:
            sftp.close()
        logger.info("已上传 %d 字节到 %s", len(content), remote_path)


    # ------------------------------------------------------------------
    # Ansible 命令构建 & 执行
    # ------------------------------------------------------------------

    def _build_ansible_cmd(
        self,
        target: str,
        *,
        module: Optional[str] = None,
        args: Optional[str] = None,
        become: Optional[bool] = None,
        extra_opts: str = "",
    ) -> str:
        """构建完整的 ansible 命令行。"""
        parts = ["ansible", target, "-i", self._inventory_path]

        if module:
            parts.extend(["-m", module])
        if args:
            parts.extend(["-a", args])

        use_become = become if become is not None else self._become
        if use_become:
            parts.append("--become")
            if self._become_user != "root":
                parts.extend(["--become-user", self._become_user])

        if extra_opts:
            parts.extend(shlex.split(extra_opts))

        return " ".join(shlex.quote(part) for part in parts)

    def ansible_command(
        self,
        target: str,
        command: str,
        become: Optional[bool] = None,
        timeout: Optional[int] = None,
    ) -> tuple[int, str, str]:
        """执行 ansible ad-hoc 命令 (raw shell command).

        等价于: ansible <target> -i <inventory> -a '<command>' [--become]
        """
        cmd = self._build_ansible_cmd(target, args=command, become=become)
        return self.execute(cmd, timeout=timeout)

    def ansible_module(
        self,
        target: str,
        module: str,
        args: str,
        become: Optional[bool] = None,
        timeout: Optional[int] = None,
    ) -> tuple[int, str, str]:
        """执行 ansible 模块调用。

        等价于: ansible <target> -i <inventory> -m <module> -a '<args>' [--become]
        """
        cmd = self._build_ansible_cmd(
            target, module=module, args=args, become=become
        )
        return self.execute(cmd, timeout=timeout)

    def ansible_playbook(
        self,
        playbook_content: str,
        target: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> tuple[int, str, str]:
        """执行 Ansible Playbook。

        将 playbook YAML 内容上传到 Ubuntu 临时文件后执行。
        """
        remote_dir = "/tmp"
        temp_name = f"ansible_playbook_{uuid.uuid4().hex[:8]}.yml"
        remote_path = os.path.join(remote_dir, temp_name).replace("\\", "/")

        # 上传 playbook
        self.upload_content(playbook_content, remote_path)

        # 构建命令
        parts = ["ansible-playbook", "-i", self._inventory_path, remote_path]
        if target:
            parts.extend(["-l", target])
        if self._become:
            parts.append("--become")

        cmd = " ".join(shlex.quote(part) for part in parts)

        # 执行并清理
        try:
            return self.execute(cmd, timeout=timeout)
        finally:
            # 清理临时文件
            self.execute(f"rm -f {shlex.quote(remote_path)}")

    def ansible_ping(self, target: str) -> tuple[bool, str]:
        """使用 ansible ping 模块测试主机连通性。"""
        exit_code, stdout, stderr = self.ansible_module(
            target, module="ping", args="", become=False
        )
        success = exit_code == 0 and "SUCCESS" in stdout
        output = stdout if stdout else stderr
        return success, output

    def ansible_facts(self, target: str) -> tuple[bool, str]:
        """使用 setup 模块获取主机 facts。"""
        exit_code, stdout, stderr = self.ansible_module(
            target, module="setup", args="", become=False, timeout=60
        )
        success = exit_code == 0
        output = stdout if stdout else stderr
        return success, output

    def ansible_list_inventory(self) -> str:
        """列出 inventory 文件内容。"""
        exit_code, stdout, stderr = self.execute(
            f"cat {shlex.quote(self._inventory_path)}"
        )
        if exit_code != 0:
            self.execute(f"mkdir -p $(dirname {shlex.quote(self._inventory_path)})")
            return (
                f"Inventory 文件不存在 ({self._inventory_path})。"
                f"请先运行 ansible_setup。"
            )
        return stdout

    def ansible_add_host(
        self,
        name: str,
        host: str,
        user: str,
        groups: Optional[list[str]] = None,
    ) -> str:
        """向 inventory 追加一个主机条目。"""
        remote_dir = os.path.dirname(self._inventory_path)
        self.execute(f"mkdir -p {shlex.quote(remote_dir)}")

        entry = f"{name} ansible_host={host} ansible_user={user}"
        exit_code, current, _ = self.execute(
            f"cat {shlex.quote(self._inventory_path)}"
        )
        if exit_code != 0:
            current = "# Managed by Ansible MCP Server\n\n[all]\n"

        lines = current.rstrip().splitlines()
        if entry not in lines:
            if "[all]" not in lines:
                lines.extend(["", "[all]"])
            insert_at = lines.index("[all]") + 1
            while insert_at < len(lines) and lines[insert_at].strip() and not lines[insert_at].startswith("["):
                insert_at += 1
            lines.insert(insert_at, entry)

        if groups:
            for group in groups:
                header = f"[{group}]"
                if header not in lines:
                    lines.extend(["", header, name])
                    continue
                idx = lines.index(header) + 1
                members = []
                while idx < len(lines) and lines[idx].strip() and not lines[idx].startswith("["):
                    members.append(lines[idx].strip())
                    idx += 1
                if name not in members:
                    lines.insert(idx, name)
            result = (
                f"已添加主机 {name} ({host}, user={user}) "
                f"到分组 {groups}"
            )
        else:
            result = f"已添加主机 {name} ({host}, user={user})"

        self.upload_content("\n".join(lines).rstrip() + "\n", self._inventory_path)
        return result

    @property
    def inventory_path(self) -> str:
        return self._inventory_path

    def download_content(self, remote_path: str) -> str:
        """通过 SFTP 下载远程文件内容。"""
        self._ensure_connected()
        sftp = self._client.open_sftp()
        try:
            with sftp.file(remote_path, "r") as f:
                return f.read().decode("utf-8", errors="replace")
        finally:
            sftp.close()
