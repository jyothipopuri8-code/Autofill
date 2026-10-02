// Content scripts run next to untrusted pages, so they get an allow-list of agent calls rather than a general
// proxy. Everything that reads or changes the profile, answer library, resumes, settings or stored data is
// reachable only from the extension's own pages (the popup).
const ALLOWED: Array<[RegExp, string[]]> = [
  [/^\/api\/v1\/status$/, ["GET"]],
  [/^\/api\/v1\/settings$/, ["GET"]],
  [/^\/api\/v1\/sessions$/, ["GET", "POST"]],
  [/^\/api\/v1\/sessions\?[A-Za-z0-9_=&%.:/-]*$/, ["GET"]],
  [/^\/api\/v1\/sessions\/\d+$/, ["GET", "PATCH"]],
  [/^\/api\/v1\/sessions\/\d+\/(analyze|answers|fill-report|validate|resume|conflicts\/resolve)$/, ["POST"]],
  [/^\/api\/v1\/sessions\/\d+\/(attention|final-review|resume-file)$/, ["GET"]],
  [/^\/api\/v1\/applications\/\d+$/, ["PATCH"]],
];

export function allowed(method: string, path: string): boolean {
  return ALLOWED.some(([re, methods]) => re.test(path) && methods.includes(method));
}
