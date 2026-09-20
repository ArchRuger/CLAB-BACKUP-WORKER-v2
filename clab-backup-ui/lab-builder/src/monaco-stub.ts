// The builder ships without the editor's YAML and JSON tabs (their schema validator needs script
// evaluation the manager's policy refuses), yet the editor preloads its code editor shortly after
// mounting. This stands in for that chunk so several megabytes are neither bundled nor downloaded.
export const MonacoCodeEditor = () => null;
