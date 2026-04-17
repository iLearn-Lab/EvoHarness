import React from 'react';
import {Box, Text} from 'ink';

import type {TranscriptItem} from '../types.js';

const READ_FILE_PREVIEW_LINES = 10;
const GENERIC_MAX_LINES = 80;
const GENERIC_MAX_CHARS = 8000;

type SubagentPayload = {
	agent_name?: string;
	summary?: string;
	turn_count?: number;
	tool_count?: number;
	stop_reason?: string | null;
	tool_names?: string[];
	model_name?: string | null;
};

export function ToolCallDisplay({item}: {item: TranscriptItem}): React.JSX.Element {
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
		const displayText = formatToolResultForUi(item);
		return (
			<Box marginTop={1} marginLeft={2} flexDirection="column" borderStyle="round" borderColor={item.is_error ? 'red' : 'green'} paddingX={1}>
				<Text color={item.is_error ? 'red' : 'green'} bold>
					{item.is_error ? 'tool error' : 'tool result'}  ::  {item.tool_name ?? ''}
				</Text>
				{badges ? <Text dimColor>{badges}</Text> : null}
				{displayText ? (
					<Text color={item.is_error ? 'red' : undefined}>{displayText}</Text>
				) : (
					<Text dimColor>(no output)</Text>
				)}
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
		.join('  -  ');

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
		return `${String(toolInput.name)} :: ${String(toolInput.task ?? '').slice(0, 90)}`;
	}
	if (toolInput.path) {
		const segment = toolInput.segment;
		if (segment !== undefined) {
			return `${String(toolInput.path)} :: segment ${String(segment)}`;
		}
		return String(toolInput.path);
	}
	if (toolInput.pattern) {
		const offset = toolInput.offset;
		return offset !== undefined ? `${String(toolInput.pattern)} :: offset ${String(offset)}` : String(toolInput.pattern);
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

	return badges.join('  -  ');
}

function formatToolResultForUi(item: TranscriptItem): string {
	if (!item.text) {
		return '';
	}

	if (!item.is_error && item.tool_name === 'read_file') {
		return compactReadFileOutput(item);
	}

	return compactGenericOutput(item.text);
}

function compactReadFileOutput(item: TranscriptItem): string {
	const metadata = item.metadata ?? {};
	const {summary, content} = splitFileView(item.text);
	const contentLines = content ? content.split('\n') : [];
	const shouldCompact = contentLines.length > READ_FILE_PREVIEW_LINES || item.text.length > GENERIC_MAX_CHARS;
	if (!shouldCompact) {
		return item.text;
	}

	const preview = contentLines.slice(0, READ_FILE_PREVIEW_LINES).join('\n').trimEnd();
	const hiddenLines = Math.max(0, contentLines.length - READ_FILE_PREVIEW_LINES);
	const path = typeof metadata.path === 'string' ? metadata.path : '';
	const range = buildSelectedRange(metadata);
	const summaryLines = [
		'[file view compacted for UI]',
		path ? `path: ${path}` : '',
		range ? `selected: ${range}` : '',
		summary ? summary.replace('[file summary]\n', '') : '',
	]
		.filter(Boolean)
		.join('\n');

	return [
		summaryLines,
		'',
		'[file content preview]',
		preview || '(empty preview)',
		hiddenLines > 0 ? `... ${hiddenLines} more selected lines hidden in UI; the model still received the tool output.` : '',
	]
		.filter(Boolean)
		.join('\n');
}

function compactGenericOutput(text: string): string {
	const lines = text.split('\n');
	if (lines.length <= GENERIC_MAX_LINES && text.length <= GENERIC_MAX_CHARS) {
		return text;
	}

	const previewLines = lines.slice(0, GENERIC_MAX_LINES);
	const preview = previewLines.join('\n');
	const hiddenLines = Math.max(0, lines.length - previewLines.length);
	const hiddenChars = Math.max(0, text.length - preview.length);
	return [
		'[tool output compacted for UI]',
		preview,
		`... hidden in UI: ${hiddenLines} lines, ${hiddenChars} chars. The model still received the tool output.`,
	].join('\n');
}

function splitFileView(text: string): {summary: string; content: string} {
	const marker = '\n[file content]\n';
	const markerIndex = text.indexOf(marker);
	if (markerIndex < 0) {
		return {summary: '', content: text};
	}
	return {
		summary: text.slice(0, markerIndex).trim(),
		content: text.slice(markerIndex + marker.length),
	};
}

function buildSelectedRange(metadata: Record<string, unknown>): string {
	const start = typeof metadata.segment_start_line === 'number' ? metadata.segment_start_line : undefined;
	const end = typeof metadata.segment_end_line === 'number' ? metadata.segment_end_line : undefined;
	const segment = typeof metadata.segment_index === 'number' ? metadata.segment_index : undefined;
	const segmentCount = typeof metadata.segment_count === 'number' ? metadata.segment_count : undefined;
	if (segment && segmentCount && start && end) {
		return `segment ${segment}/${segmentCount}, lines ${start}-${end}`;
	}
	if (start && end) {
		return `lines ${start}-${end}`;
	}
	return '';
}
