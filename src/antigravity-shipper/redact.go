package main

import (
	"regexp"
)

var (
	// PEM private key blocks
	rePEMBlock = regexp.MustCompile(`(?s)-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----`)

	// Standard Authorization and Bearer headers
	reAuthHeader = regexp.MustCompile(`(?i)\bAuthorization:\s*(Bearer\s+|Basic\s+)?[^\s'"]+`)
	reBearer     = regexp.MustCompile(`(?i)\bBearer\s+[A-Za-z0-9\-\._~\+\/]+=*`)

	// Token patterns: OpenAI (sk-, sk-ant-), Slack (xox*), Google (AIza), GitHub (ghp, github_pat), AWS (AKIA)
	reOpenAIKey    = regexp.MustCompile(`\b(sk-[A-Za-z0-9_-]{20,}|sk-ant-[A-Za-z0-9_-]{20,})\b`)
	reSlackToken   = regexp.MustCompile(`\bxox[bpa]-[0-9A-Za-z_-]{10,}\b`)
	reGoogleKey    = regexp.MustCompile(`\bAIza[0-9A-Za-z-_]{30,45}\b`)
	reGitHubToken  = regexp.MustCompile(`\b(gh[pousr]_[A-Za-z0-9_]{10,}|github_pat_[A-Za-z0-9_]{10,})\b`)
	reAWSAccessKey = regexp.MustCompile(`\bAKIA[0-9A-Z]{16}\b`)

	// JWTs: eyJ...ey...
	reJWT = regexp.MustCompile(`\bey[A-Za-z0-9_-]{10,}\.ey[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+\b`)

	// URL credentials: user:pass@ in authority only (cannot contain / or whitespace)
	reURLCreds = regexp.MustCompile(`(://[^:/\s'"]+):([^@/\s'"]+)@`)

	// curl -u user:pass (handles optional quotes around credentials)
	reCurlAuth = regexp.MustCompile(`(?i)(\bcurl\b[^\n|;&]*-u\s+["']?[^:\s'"]+):([^\s'"]+)(["']?)`)

	// CLI password flags restricted to database/auth contexts (mysql, mariadb, sshpass)
	reCliPass = regexp.MustCompile(`(?i)(\b(?:mysql|mysqldump|mariadb|sshpass)\b[^\n|;&]*-p\s*=?\s*)([^\s"'>;&]+)`)

	// Generic secret variable assignments: key[:=]value with optional quotes and prefixes (e.g. DB_PASSWORD=foo, "token": "xyz", :_authToken=npm_...)
	reGenericSecret = regexp.MustCompile(`(?i)(["']?[:_A-Za-z0-9_-]*(?:token|secret|password|passwd|api[_-]?key|auth[_-]?token)[:_A-Za-z0-9_-]*["']?\s*[:=]\s*)(["']?)([^\s"'>;&]+)(["']?)`)
)

// RedactSecrets replaces sensitive tokens, passwords, and API keys with [REDACTED].
func RedactSecrets(s string) string {
	if s == "" {
		return ""
	}
	s = rePEMBlock.ReplaceAllString(s, "[REDACTED PRIVATE KEY]")
	s = reAuthHeader.ReplaceAllString(s, "Authorization: [REDACTED]")
	s = reBearer.ReplaceAllString(s, "Bearer [REDACTED]")
	s = reOpenAIKey.ReplaceAllString(s, "[REDACTED]")
	s = reSlackToken.ReplaceAllString(s, "[REDACTED]")
	s = reGoogleKey.ReplaceAllString(s, "[REDACTED]")
	s = reGitHubToken.ReplaceAllString(s, "[REDACTED]")
	s = reAWSAccessKey.ReplaceAllString(s, "[REDACTED]")
	s = reJWT.ReplaceAllString(s, "[REDACTED]")
	s = reURLCreds.ReplaceAllString(s, "$1:[REDACTED]@")
	s = reCurlAuth.ReplaceAllString(s, "$1:[REDACTED]$3")
	s = reCliPass.ReplaceAllString(s, "${1}[REDACTED]")
	s = reGenericSecret.ReplaceAllString(s, "${1}${2}[REDACTED]${4}")
	return s
}

// Truncate cuts a string to maxRunes, adding an ellipsis if truncated.
// It is safely guarded against limits < 3.
func Truncate(s string, maxRunes int) string {
	if maxRunes <= 0 {
		return s
	}
	runes := []rune(s)
	if len(runes) <= maxRunes {
		return s
	}
	if maxRunes < 3 {
		return string(runes[:maxRunes])
	}
	return string(runes[:maxRunes-3]) + "..."
}

// Sanitize applies secret redaction followed by length truncation.
func Sanitize(s string, maxRunes int) string {
	return Truncate(RedactSecrets(s), maxRunes)
}
