package main

import (
	"testing"
)

func TestRedactSecrets_Table(t *testing.T) {
	cases := []struct {
		name     string
		input    string
		expected string
	}{
		{
			name:     "Authorization Bearer Header",
			input:    "curl -H 'Authorization: Bearer secret_token_123' https://api.example.com",
			expected: "curl -H 'Authorization: [REDACTED]' https://api.example.com",
		},
		{
			name:     "GitHub Token with Prefix",
			input:    "export GH_TOKEN=" + "ghp_" + "ABC1234567890abcdefghijklmnopqrstuvwxyz",
			expected: "export GH_TOKEN=[REDACTED]",
		},
		{
			name:     "OpenAI API Key with Prefix",
			input:    "export OPENAI_API_KEY=" + "sk-" + "proj-1234567890abcdefghijklmnop",
			expected: "export OPENAI_API_KEY=[REDACTED]",
		},
		{
			name:     "Anthropic API Key standalone",
			input:    "sk-ant-" + "api03-1234567890abcdefghijklmnop",
			expected: "[REDACTED]",
		},
		{
			name:     "DB Password with Prefix",
			input:    "connect --DB_PASSWORD=supersecretpassword123",
			expected: "connect --DB_PASSWORD=[REDACTED]",
		},
		{
			name:     "JSON Quoted Password Value",
			input:    `{"DB_PASSWORD": "hunter2"}`,
			expected: `{"DB_PASSWORD": "[REDACTED]"}`,
		},
		{
			name:     "NPM Auth Token",
			input:    "//registry.npmjs.org/:_authToken=npm_1234567890abcdef",
			expected: "//registry.npmjs.org/:_authToken=[REDACTED]",
		},
		{
			name:     "AWS Secret Access Key",
			input:    "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
			expected: "AWS_SECRET_ACCESS_KEY=[REDACTED]",
		},
		{
			name:     "AWS Access Key ID standalone",
			input:    "aws configure set aws_access_key_id " + "AKIA" + "IOSFODNN7EXAMPLE",
			expected: "aws configure set aws_access_key_id [REDACTED]",
		},
		{
			name:     "URL Query Parameter access_token",
			input:    "https://api.example.com/data?access_token=secret12345",
			expected: "https://api.example.com/data?access_token=[REDACTED]",
		},
		{
			name:     "Slack Bot Token",
			input:    "xoxb" + "-1234567890-1234567890123-abcdefghijklmnop",
			expected: "[REDACTED]",
		},
		{
			name:     "Google API Key",
			input:    "AIza" + "SyD1234567890abcdefghijklmnopqrstuvw",
			expected: "[REDACTED]",
		},
		{
			name:     "JWT Token",
			input:    "token: " + "ey" + "JhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9." + "ey" + "JzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
			expected: "token: [REDACTED]",
		},
		{
			name:     "Database URL with user:pass",
			input:    "postgres://admin:secretpass123@localhost:5432/mydb",
			expected: "postgres://admin:[REDACTED]@localhost:5432/mydb",
		},
		{
			name:     "curl -u user:pass unquoted",
			input:    "curl -u myuser:secretpass123 https://api.example.com",
			expected: "curl -u myuser:[REDACTED] https://api.example.com",
		},
		{
			name:     "curl -u user:pass quoted",
			input:    `curl -u "admin:hunter2" https://api.example.com`,
			expected: `curl -u "admin:[REDACTED]" https://api.example.com`,
		},
		{
			name:     "CLI password flag mysql -p",
			input:    "mysql -u root -psecretpassword123 dbname",
			expected: "mysql -u root -p[REDACTED] dbname",
		},
		{
			name:     "CLI password flag sshpass -p",
			input:    "sshpass -p hunter2 ssh user@host",
			expected: "sshpass -p [REDACTED] ssh user@host",
		},
		{
			name:     "PEM Private Key Block",
			input:    "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0abc...\n-----END RSA PRIVATE KEY-----",
			expected: "[REDACTED PRIVATE KEY]",
		},
		// Negative cases: MUST NOT be redacted
		{
			name:     "Negative: mkdir -p flag",
			input:    "mkdir -p /tmp/foo/bar",
			expected: "mkdir -p /tmp/foo/bar",
		},
		{
			name:     "Negative: git log -p flag",
			input:    "git log -p HEAD~3",
			expected: "git log -p HEAD~3",
		},
		{
			name:     "Negative: ripgrep password",
			input:    "rg password internal/",
			expected: "rg password internal/",
		},
		{
			name:     "Negative: grep token",
			input:    "grep -rn token src/",
			expected: "grep -rn token src/",
		},
		{
			name:     "Negative: echo monkey business",
			input:    "echo monkey business",
			expected: "echo monkey business",
		},
		{
			name:     "Negative: URL with @ in path",
			input:    "https://host:8080/a@b",
			expected: "https://host:8080/a@b",
		},
		{
			name:     "Negative: git checkout",
			input:    "git checkout -b feature-branch",
			expected: "git checkout -b feature-branch",
		},
		{
			name:     "Negative: keyboard layout",
			input:    "set keyboard layout to us",
			expected: "set keyboard layout to us",
		},
		{
			name:     "Negative: cat file",
			input:    "cat /etc/hosts",
			expected: "cat /etc/hosts",
		},
	}

	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			out := RedactSecrets(c.input)
			if out != c.expected {
				t.Errorf("RedactSecrets(%q)\ngot:  %q\nwant: %q", c.input, out, c.expected)
			}
		})
	}
}

func TestTruncate_Guards(t *testing.T) {
	if got := Truncate("hello", 0); got != "hello" {
		t.Errorf("expected 'hello', got %q", got)
	}
	if got := Truncate("hello", -5); got != "hello" {
		t.Errorf("expected 'hello', got %q", got)
	}
	if got := Truncate("hello", 2); got != "he" {
		t.Errorf("expected 'he', got %q", got)
	}
	if got := Truncate("hello", 1); got != "h" {
		t.Errorf("expected 'h', got %q", got)
	}
	if got := Truncate("hello world", 6); got != "hel..." {
		t.Errorf("expected 'hel...', got %q", got)
	}
}

func TestSanitize(t *testing.T) {
	secretStr := "connect --DB_PASSWORD=supersecretpassword123 to database"
	got := Sanitize(secretStr, 35)
	expected := "connect --DB_PASSWORD=[REDACTED]..."
	if got != expected {
		t.Errorf("Sanitize got %q, want %q", got, expected)
	}
}

func TestExtractCommandBinary(t *testing.T) {
	cases := []struct {
		input    string
		expected string
	}{
		{"git status", "git"},
		{"git -C /path log", "git"},
		{"FOO=bar BAZ=1 git commit -m \"msg\"", "git"},
		{"sudo systemctl restart nginx", "systemctl"},
		{"env DEBUG=1 podman ps -a", "podman"},
		{"uv run python app/main.py", "uv"},
		{"/usr/local/bin/docker compose up", "docker"},
		{"curl -s https://example.com", "curl"},
		{"rg -n 'pattern' .", "rg"},
		{"", ""},
	}

	for _, c := range cases {
		got := ExtractCommandBinary(c.input)
		if got != c.expected {
			t.Errorf("ExtractCommandBinary(%q) = %q, want %q", c.input, got, c.expected)
		}
	}
}
