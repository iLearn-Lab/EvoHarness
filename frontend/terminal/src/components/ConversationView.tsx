import React, {memo, useMemo} from 'react';
import {Box, Text} from 'ink';

import type {TranscriptItem} from '../types.js';
import {ToolCallDisplay} from './ToolCallDisplay.js';
import {WelcomeBanner} from './WelcomeBanner.js';

type ConversationViewProps = {
	items: TranscriptItem[];
	assistantBuffer: string;
	showWelcome: boolean;
	status: Record<string, unknown>;
	maxVisibleLines: number;
	terminalWidth: number;
	expandedResultIds: string[];
	latestExpandableId?: string;
	messageOffset: number;
};

function ConversationViewInner({
	items,
	assistantBuffer,
	showWelcome,
	status,
	maxVisibleLines,
	terminalWidth,
	expandedResultIds,
	latestExpandableId,
	messageOffset,
}: ConversationViewProps): React.JSX.Element {
	const {visibleItems, clippedOlderCount, clippedNewerCount} = useMemo(
		() => selectVisibleItems(items, maxVisibleLines, terminalWidth, assistantBuffer, expandedResultIds, messageOffset),
		[assistantBuffer, expandedResultIds, items, maxVisibleLines, messageOffset, terminalWidth],
	);

	return (
		<Box flexDirection="column" flexGrow={1}>
			{showWelcome && items.length === 0 ? <WelcomeBanner status={status} /> : null}
			{clippedOlderCount > 0 ? (
				<Text dimColor>
					[older {clippedOlderCount} messages available :: page up or ctrl+up]
				</Text>
			) : null}
			{clippedNewerCount > 0 ? (
				<Text dimColor>
					[newer {clippedNewerCount} messages below :: page down or ctrl+down]
				</Text>
			) : null}
			{visibleItems.map((item, index) => (
				<MessageRow
					key={item.id ?? `${item.role}-${item.tool_name ?? 'msg'}-${index}`}
					item={item}
					expanded={Boolean(item.id && expandedResultIds.includes(item.id))}
					highlightExpandable={Boolean(item.id && latestExpandableId === item.id)}
				/>
			))}
			{assistantBuffer ? (
				<Box marginTop={1} borderStyle="round" borderColor="green" paddingX={1} flexDirection="column">
					<Text color="green" bold>assistant streaming  ::  building the next turn (^_^)/</Text>
					<Text>{assistantBuffer}</Text>
				</Box>
			) : null}
		</Box>
	);
}

export const ConversationView = memo(ConversationViewInner);

function MessageRow({
	item,
	expanded,
	highlightExpandable,
}: {
	item: TranscriptItem;
	expanded: boolean;
	highlightExpandable: boolean;
}): React.JSX.Element {
	switch (item.role) {
		case 'user':
			return (
				<MessagePanel accent="cyan" label="you" mood="(^_^)/">
					<Text>{item.text}</Text>
				</MessagePanel>
			);
		case 'assistant':
			return (
				<MessagePanel accent="green" label="assistant" mood="(^_^)/">
					<Text>{item.text}</Text>
				</MessagePanel>
			);
		case 'tool':
		case 'tool_result':
			return <ToolCallDisplay item={item} expanded={expanded} highlightExpandable={highlightExpandable} />;
		case 'system':
			return (
				<MessagePanel accent="yellow" label="system" mood="( -_- )">
					<Text color="yellow">{item.text}</Text>
				</MessagePanel>
			);
		case 'log':
			return (
				<Box marginTop={1}>
					<Text dimColor>{item.text}</Text>
				</Box>
			);
		default:
			return (
				<Box marginTop={1}>
					<Text>{item.text}</Text>
				</Box>
			);
	}
}

function MessagePanel({
	accent,
	label,
	mood,
	children,
}: {
	accent: 'cyan' | 'green' | 'yellow';
	label: string;
	mood: string;
	children: React.ReactNode;
}): React.JSX.Element {
	return (
		<Box marginTop={1} flexDirection="column">
			<Text color={accent} bold>
				{label}  {mood}
			</Text>
			<Box marginLeft={2}>{children}</Box>
		</Box>
	);
}

function selectVisibleItems(
	items: TranscriptItem[],
	maxVisibleLines: number,
	terminalWidth: number,
	assistantBuffer: string,
	expandedResultIds: string[],
	messageOffset: number,
): {visibleItems: TranscriptItem[]; clippedOlderCount: number; clippedNewerCount: number} {
	if (items.length === 0) {
		return {visibleItems: items, clippedOlderCount: 0, clippedNewerCount: 0};
	}

	const available = Math.max(4, maxVisibleLines - estimateStreamingLines(assistantBuffer, terminalWidth));
	const kept: TranscriptItem[] = [];
	let used = 0;
	const newestIndex = Math.max(0, items.length - 1 - messageOffset);

	for (let index = newestIndex; index >= 0; index--) {
		const item = items[index];
		const expanded = Boolean(item.id && expandedResultIds.includes(item.id));
		const cost = estimateItemLines(item, terminalWidth, expanded);
		if (kept.length > 0 && used + cost > available) {
			break;
		}
		kept.push(item);
		used += cost;
	}

	kept.reverse();
	return {
		visibleItems: kept,
		clippedOlderCount: Math.max(0, items.length - kept.length - messageOffset),
		clippedNewerCount: Math.max(0, messageOffset),
	};
}

function estimateItemLines(item: TranscriptItem, width: number, expanded: boolean): number {
	switch (item.role) {
		case 'user':
		case 'assistant':
		case 'system':
			return 1 + estimateWrappedTextLines(item.text, width - 4) + 1;
		case 'tool':
			return 4;
		case 'tool_result':
			if (isExpandableToolResult(item) && !expanded) {
				return 5;
			}
			return 3 + Math.min(item.text.split('\n').length, expanded ? 18 : 8);
		case 'log':
			return Math.max(1, estimateWrappedTextLines(item.text, width - 2));
		default:
			return Math.max(1, estimateWrappedTextLines(item.text, width - 2));
	}
}

function estimateStreamingLines(text: string, width: number): number {
	if (!text) {
		return 0;
	}
	return 3 + estimateWrappedTextLines(text, width - 4);
}

function estimateWrappedTextLines(text: string, width: number): number {
	const safeWidth = Math.max(12, width);
	const segments = text.split('\n');
	let total = 0;
	for (const segment of segments) {
		const length = segment.length || 1;
		total += Math.max(1, Math.ceil(length / safeWidth));
	}
	return total;
}

function isExpandableToolResult(item: TranscriptItem): boolean {
	if (item.role !== 'tool_result' || item.tool_name === 'run_subagent') {
		return false;
	}
	const lines = item.text.split('\n');
	return lines.length > 6 || item.text.length > 260;
}
