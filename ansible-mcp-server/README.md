# Ansible MCP Server

Ansible MCP Server exposes a small set of Ansible operations as MCP tools. It is designed for a local AI client such as Claude Desktop to manage lab VMs through an Ubuntu Ansible controller.

## Architecture

```text
AI client / MCP host
  |
  | stdio
  v
Windows: server.py
  |
  | Paramiko SSH
  v
Ubuntu Ansible controller
  |
  | Ansible SSH
  v
Managed Linux nodes
```

## Features

- Initialize a lab Ansible environment with SSH key generation, key distribution, inventory generation, and connectivity checks.
- Run Ansible ping, ad-hoc commands, modules, and playbooks.
- List and extend the remote inventory.
- Fetch Ansible facts from managed nodes.

## Requirements

- Python 3.11 or newer
- Ansible installed on the Ubuntu controller node
- SSH access from this server to the Ubuntu controller
- SSH access from the Ubuntu controller to the managed nodes after setup

Install Python dependencies:

```powershell
pip install -r requirements.txt
```

## Configuration

Copy the example configuration and fill in values for your own lab:

```powershell
Copy-Item config.yaml config.local.yaml
```

`config.local.yaml` is ignored by Git and should contain real IP addresses, users, and credentials. The server loads configuration in this order:

1. `ANSIBLE_MCP_CONFIG` environment variable, if set
2. `config.local.yaml`
3. `config.yaml`

Do not commit real passwords, private keys, inventory files, or logs.

## Claude Desktop Example

Update your Claude Desktop config with the path to `server.py`:

```json
{
  "mcpServers": {
    "ansible": {
      "command": "python",
      "args": ["C:\\Users\\your-user\\ansible-mcp-server\\server.py"]
    }
  }
}
```

Restart Claude Desktop after editing the config.

## MCP Tools

- `ansible_setup()`: initialize SSH keys, inventory, and connectivity.
- `ansible_ping(target)`: run Ansible ping against a host or group.
- `ansible_run_command(target, command, become=False)`: run an ad-hoc shell command through Ansible.
- `ansible_run_module(target, module, args, become=False)`: run an Ansible module.
- `ansible_run_playbook(playbook_content, target="")`: upload and run a playbook.
- `ansible_get_facts(target)`: collect facts with the setup module.
- `ansible_list_inventory()`: show the remote inventory.
- `ansible_add_host(name, host, user, groups=None)`: append a host to inventory.
- `ansible_exec_shell(command)`: run a shell command directly on the controller.

## Security Notes

This project can execute privileged commands on managed machines. Treat it as an operator tool, not as a public API.

- Keep `config.local.yaml` private.
- Prefer SSH key authentication over passwords.
- Restrict who can start or call this MCP server.
- Review commands before running destructive operations.
- Consider disabling `ansible_exec_shell` outside a private lab.

## Development

The project is intentionally small:

- `server.py`: FastMCP entry point and tool definitions
- `ansible_runner.py`: SSH connection and Ansible command execution
- `setup_helper.py`: first-run setup workflow
- `config.yaml`: public example configuration
