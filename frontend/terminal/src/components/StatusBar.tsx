import React, {memo} from 'react';
import {Box, Text} from 'ink';

import type {TaskSnapshot} from '../types.js';

function StatusBarInner({status, tasks}: {status: Record<string, unknown>; tasks: TaskSnapshot[]}): React.JSX.Element {
	const model = String(status.model ?? 'unknown');
	const mode = String(status.permission_mode ?? 'default');
	const provider = String(status.provider ?? 'provider');
	const cwd = String(status.cwd ?? '');
	const workspace = cwd.split(/[\\/]/).filter(Boolean).pop() ?? (cwd || 'workspace');
	const activeCommand = String(status.active_command ?? '');
	const pendingApprovals = Number(status.pending_approvals ?? 0);
	const taskCount = tasks.length;
	const inputTokens = Number(status.input_tokens ?? 0);
	const outputTokens = Number(status.output_tokens ?? 0);
	const commands = Number(status.command_count ?? 0);
	const skills = Number(status.skill_count ?? 0);
	const agents = Number(status.agent_count ?? 0);
	const plugins = Number(status.plugin_count ?? 0);
	const mcpServers = Number(status.mcp_server_count ?? 0);
	const mcpTools = Number(status.mcp_tool_count ?? 0);
	const sessions = Number(status.session_count ?? 0);

	return (
		<Box flexDirection="column" marginTop={1} borderStyle="round" borderColor="gray" paddingX={1}>
			<Text>
				<Text color="gray">runtime :: </Text>
				<Text color="cyan" bold>{workspace}</Text>
				<Text dimColor>{'  -  '}</Text>
				<Text color="magenta">{provider}</Text>
				<Text dimColor>{'  -  '}</Text>
				<Text color="green">{model}</Text>
				<Text dimColor>{'  -  '}</Text>
				<Text color={modeColor(mode)}>{mode}</Text>
				{activeCommand ? (
					<>
						<Text dimColor>{'  -  '}</Text>
						<Text color="yellow">/{activeCommand}</Text>
					</>
				) : null}
			</Text>
			<Text dimColor>
				pulse: tasks {taskCount}  -  approvals {pendingApprovals}  -  sessions {sessions}  -  tokens {formatNum(inputTokens)} / {formatNum(outputTokens)}  -  surface {commands}/{skills}/{agents}/{plugins}/{mcpServers}:{mcpTools}
			</Text>
		</Box>
	);
}

export const StatusBar = memo(StatusBarInner);

function formatNum(value: number): string {
	if (value >= 1_000_000) {
		return `${(value / 1_000_000).toFixed(1)}m`;
	}
	if (value >= 1_000) {
		return `${(value / 1_000).toFixed(1)}k`;
	}
	return String(value);
}

function modeColor(mode: string): 'yellow' | 'green' | 'red' | 'cyan' {
	if (mode === 'full-access') {
		return 'green';
	}
	if (mode === 'plan') {
		return 'yellow';
	}
	if (mode === 'default') {
		return 'cyan';
	}
	return 'red';
}
