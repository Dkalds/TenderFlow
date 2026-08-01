// graphify OpenCode plugin
// Injects a knowledge graph reminder before the first search command when the graph exists.
import { existsSync } from "fs";
import { join } from "path";

const SEARCH_COMMAND = /(^|[;&|\s])(grep|rg|ripgrep|find|fd|ack|ag)(\s|$)/;
const REMINDER =
  '[graphify] Knowledge graph available in graphify-out/. Use graphify query "<question>" when the CLI exists; otherwise read the committed artifacts before searching raw files.';

export const GraphifyPlugin = async ({ directory }) => {
  let reminded = false;

  return {
    "tool.execute.before": async (input, output) => {
      if (reminded) return;
      if (!existsSync(join(directory, "graphify-out", "graph.json"))) return;

      if (input.tool !== "bash" || !SEARCH_COMMAND.test(output.args.command)) return;

      output.args.command = `printf '%s\\n' '${REMINDER}' && ${output.args.command}`;
      reminded = true;
    },
  };
};
