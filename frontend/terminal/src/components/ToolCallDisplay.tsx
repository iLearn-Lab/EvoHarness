import React from 'react';
import {Box, Text} from 'ink';

import type {TranscriptItem} from '../types.js';

type SubagentPayload = {
	agent_name?: string;
	summary?: string;
	turn_count?: number;
	tool_count?: number;
	stop_reason?: string | null;
	tool_names?: string[];
	model_name?: string | null;
};

export function ToolCallDisplay({
	item,
	expanded = false,
	highlightExpandable = false,
}: {
	item: TranscriptItem;
	expanded?: boolean;
	highlightExpandable?: boolean;
}): React.JSX.Element {
	if (item.role === 'tool') {
		const toolName = item.tool_name ?? 'tool';
		const summary = summarizeInput(toolName, item.tool_input, item.text);
		return (
			<Box marginTop={1} marginLeft={1} flexDirection="column" borderStyle="round" borderColor="cyan" paddingX={1}>
				<Text color="cyan" bold>
					tool deck  ::  {toolName}
				</Text>
				<Text dimColor>{summary}</Text>
			</Box>
		);
	}

	if (item.role === 'tool_result') {
		const subagent = parseSubagentPayload(item);
		if (subagent) {
			return <SubagentResultCard payload={subagent} isError={Boolean(item.is_error)} />;
		}
		const badges = buildMetadataBadges(item.metadata);
		const collapsed = isExpandableToolResult(item) && !expanded;
		const lines = item.text.split('\n');
		const visibleLines = collapsed ? lines.slice(0, 4) : lines.slice(0, 18);
		const hiddenCount = Math.max(0, lines.length - visibleLines.length);
		return (
			<Box marginTop={1} marginLeft={2} flexDirection="column" borderStyle="round" borderColor={item.is_error ? 'red' : 'green'} paddingX={1}>
				<Text color={item.is_error ? 'red' : 'green'} bold>
					{item.is_error ? 'tool error' : 'tool result'}  ::  {item.tool_name ?? ''}
				</Text>
				{badges ? <Text dimColor>{badges}</Text> : null}
				{collapsed ? (
					<Text dimColor>
						{highlightExpandable ? '[>] latest result folded  ::  press right arrow to expand' : '[>] folded result'}
					</Text>
				) : null}
				{visibleLines.map((line, index) => (
					<Text key={index} color={item.is_error ? 'red' : undefined} dimColor={!item.is_error}>
						{compactLine(line)}
					</Text>
				))}
				{hiddenCount > 0 ? (
					<Text dimColor>
						{expanded ? `[v] expanded  ::  ${hiddenCount} more lines still hidden` : `[>] ${hiddenCount} more lines hidden`}
					</Text>
				) : null}
			</Box>
		);
	}

	return <Text>{item.text}</Text>;
}

function SubagentResultCard({
	payload,
	isError,
}: {
	payload: SubagentPayload;
	isError: boolean;
}): React.JSX.Element {
	const toolNames = Array.isArray(payload.tool_names) ? payload.tool_names.join(', ') : '';
	const metrics = [
		payload.turn_count ? `turns ${payload.turn_count}` : '',
		payload.tool_count ? `tools ${payload.tool_count}` : '',
		payload.stop_reason ? `stop ${payload.stop_reason}` : '',
		payload.model_name ? `model ${payload.model_name}` : '',
	]
		.filter(Boolean)
		.join('  •  ');

	return (
		<Box marginTop={1} marginLeft={2} flexDirection="column" borderStyle="round" borderColor={isError ? 'red' : 'magenta'} paddingX={1}>
			<Text color={isError ? 'red' : 'magenta'} bold>
				subagent relay  ::  {payload.agent_name ?? 'agent'} (^_^)/
			</Text>
			{metrics ? <Text dimColor>{metrics}</Text> : null}
			{payload.summary ? <Text>{payload.summary}</Text> : null}
			{toolNames ? <Text dimColor>used: {toolNames}</Text> : null}
		</Box>
	);
}

function parseSubagentPayload(item: TranscriptItem): SubagentPayload | null {
	if (item.tool_name !== 'run_subagent') {
		return null;
	}
	try {
		const parsed = JSON.parse(item.text) as SubagentPayload;
		return typeof parsed === 'object' && parsed ? parsed : null;
	} catch {
		return null;
	}
}

function summarizeInput(toolName: string, toolInput?: Record<string, unknown>, fallback?: string): string {
	if (!toolInput) {
		return fallback?.slice(0, 100) ?? '';
	}
	const lower = toolName.toLowerCase();
	if (lower === 'bash' && toolInput.command) {
		return String(toolInput.command).slice(0, 140);
	}
	if (lower === 'run_subagent' && toolInput.name) {
		return `${String(toolInput.name)} • ${String(toolInput.task ?? '').slice(0, 90)}`;
	}
	if (toolInput.path) {
		const segment = toolInput.segment;
		if (segment !== undefined) {
			return `${String(toolInput.path)} • segment ${String(segment)}`;
		}
		return String(toolInput.path);
	}
	if (toolInput.pattern) {
		const offset = toolInput.offset;
		return offset !== undefined ? `${String(toolInput.pattern)} • offset ${String(offset)}` : String(toolInput.pattern);
	}
	const entries = Object.entries(toolInput);
	if (entries.length > 0) {
		const [key, value] = entries[0];
		return `${key}=${String(value).slice(0, 80)}`;
	}
	return fallback?.slice(0, 100) ?? '';
}

function buildMetadataBadges(metadata?: Record<string, unknown>): string {
	if (!metadata) {
		return '';
	}
	const badges: string[] = [];
	if (Boolean(metadata.segmented)) {
		if (typeof metadata.segment_index === 'number' && typeof metadata.segment_count === 'number') {
			badges.push(`segment ${metadata.segment_index}/${metadata.segment_count}`);
		} else {
			badges.push('segmented');
		}
	}
	if (typeof metadata.total_matches === 'number') {
		badges.push(`${metadata.total_matches} matches`);
	}
	if (typeof metadata.next_segment === 'number') {
		badges.push(`next segment ${metadata.next_segment}`);
	}
	if (typeof metadata.next_offset === 'number') {
		badges.push(`next offset ${metadata.next_offset}`);
	}
	return badges.join('  •  ');
}

function compactLine(line: string): string {
	if (line.length <= 180) {
		return line;
	}
	return `${line.slice(0, 177)}...`;
}

function isExpandableToolResult(item: TranscriptItem): boolean {
	if (item.role !== 'tool_result' || item.tool_name === 'run_subagent') {
		return false;
	}
	const lines = item.text.split('\n');
	return lines.length > 6 || item.text.length > 260;
}
