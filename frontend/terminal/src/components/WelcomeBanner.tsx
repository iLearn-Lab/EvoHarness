import React from 'react';
import {Box, Text} from 'ink';

const LOGO_LINES = [
	'█████  █   █  ███      █   █  ███  ████  █   █  ████   ███   ███ ',
	'█      █   █ █   █     █   █ █   █ █   █ ██  █ █      █     █    ',
	'████   █   █ █   █     █████ █████ ████  █ █ █ ███    ███   ███  ',
	'█       █ █  █   █     █   █ █   █ █  █  █  ██ █         █     █ ',
	'█████    █    ███      █   █ █   █ █   █ █   █ ████   ███   ███  ',
] as const;

export function WelcomeBanner({status}: {status?: Record<string, unknown>}): React.JSX.Element {
	const cwd = String(status?.cwd ?? '');
	const workspace = cwd.split(/[\\/]/).filter(Boolean).pop() ?? (cwd || 'workspace');
	const provider = String(status?.provider ?? 'provider');
	const model = String(status?.model ?? 'model');
	const commands = Number(status?.command_count ?? 0);
	const agents = Number(status?.agent_count ?? 0);
	const mcp = Number(status?.mcp_tool_count ?? status?.mcp_server_count ?? 0);
	const plugins = Number(status?.plugin_count ?? 0);

	return (
		<Box flexDirection="column" borderStyle="round" borderColor="cyan" paddingX={1} marginBottom={1}>
			<WindowBar />

			<Box flexDirection="column" marginBottom={1}>
				{LOGO_LINES.map((line) => (
					<Text key={line} color="cyan" bold>
						{line}
					</Text>
				))}
				<Text color="white" bold>
					Evo Harness  {'(^_^)/'}
				</Text>
			</Box>

			<Text color="gray">
				terminal-native agent runtime with commands, MCP, subagents, and a little attitude {'(^_^)/'}
			</Text>
			<Text color="magenta">make the harness feel alive, not just available {'(>ω<)'}</Text>

			<Box marginTop={1} flexDirection="row">
				<MetricPill label="workspace" value={workspace} color="white" />
				<MetricPill label="provider" value={provider} color="magenta" />
				<MetricPill label="model" value={model} color="green" />
			</Box>

			<Box marginTop={1} flexDirection="row">
				<StatPill label="commands" value={commands} />
				<StatPill label="agents" value={agents} />
				<StatPill label="mcp" value={mcp} />
				<StatPill label="plugins" value={plugins} />
			</Box>

			<Text> </Text>
			<Text>
				<Text color="cyan">/help</Text>
				<Text dimColor> guide</Text>
				<Text dimColor>{'  •  '}</Text>
				<Text color="cyan">/resume</Text>
				<Text dimColor> sessions</Text>
				<Text dimColor>{'  •  '}</Text>
				<Text color="cyan">/permissions</Text>
				<Text dimColor> mode</Text>
				<Text dimColor>{'  •  '}</Text>
				<Text color="cyan">Ctrl+C</Text>
				<Text dimColor> exit</Text>
			</Text>
		</Box>
	);
}

function WindowBar(): React.JSX.Element {
	return (
		<Box justifyContent="space-between" marginBottom={1}>
			<Text>
				<Text color="red">●</Text>
				<Text> </Text>
				<Text color="yellow">●</Text>
				<Text> </Text>
				<Text color="green">●</Text>
			</Text>
			<Text color="gray">terminal</Text>
		</Box>
	);
}

function MetricPill({
	label,
	value,
	color,
}: {
	label: string;
	value: string;
	color: 'white' | 'magenta' | 'green';
}): React.JSX.Element {
	return (
		<Box marginRight={1}>
			<Text>
				<Text color="gray">{label}</Text>
				<Text color="gray"> </Text>
				<Text color={color} bold>
					{value}
				</Text>
			</Text>
		</Box>
	);
}

function StatPill({label, value}: {label: string; value: number}): React.JSX.Element {
	return (
		<Box marginRight={2}>
			<Text>
				<Text color="cyan">{label}</Text>
				<Text color="gray"> </Text>
				<Text color="white" bold>
					{value}
				</Text>
			</Text>
		</Box>
	);
}
