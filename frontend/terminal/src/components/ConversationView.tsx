import React, {memo} from 'react';
import {Box, Static, Text} from 'ink';

import {formatAttachmentLabel} from '../attachmentUtils.js';
import type {TranscriptItem} from '../types.js';
import {ToolCallDisplay} from './ToolCallDisplay.js';
import {WelcomeBanner} from './WelcomeBanner.js';

type ConversationViewProps = {
	items: TranscriptItem[];
	assistantBuffer: string;
	showWelcome: boolean;
	status: Record<string, unknown>;
};

function ConversationViewInner({
	items,
	assistantBuffer,
	showWelcome,
	status,
}: ConversationViewProps): React.JSX.Element {
	return (
		<Box flexDirection="column" flexGrow={1}>
			{showWelcome && items.length === 0 ? <WelcomeBanner status={status} /> : null}
			{items.length > 0 ? (
				<Static items={items}>
					{(item, index) => (
						<MessageRow key={item.id ?? `${item.role}-${item.tool_name ?? 'msg'}-${index}`} item={item} />
					)}
				</Static>
			) : null}
			{assistantBuffer ? (
				<Box marginTop={1} flexDirection="column">
					<Text color="green" bold>assistant streaming :: tail</Text>
					<Box marginLeft={2}>
						<Text>{assistantBuffer}</Text>
					</Box>
				</Box>
			) : null}
		</Box>
	);
}

export const ConversationView = memo(ConversationViewInner);

function MessageRow({item}: {item: TranscriptItem}): React.JSX.Element {
	switch (item.role) {
		case 'user':
			return (
				<MessagePanel accent="cyan" label="you" mood="(^_^)/">
					<MessageBody item={item} accent="cyan" />
				</MessagePanel>
			);
		case 'assistant':
			return <AssistantMessageRow item={item} />;
		case 'tool':
		case 'tool_result':
			return <ToolCallDisplay item={item} />;
		case 'system':
			return (
				<MessagePanel accent="yellow" label="system" mood="( -_- )">
					<MessageBody item={item} accent="yellow" />
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

function AssistantMessageRow({item}: {item: TranscriptItem}): React.JSX.Element {
	const isStreaming = Boolean(item.metadata?.streaming);
	const isContinuation = Boolean(item.metadata?.continuation);

	if (isStreaming && isContinuation) {
		return (
			<Box marginLeft={2}>
				<MessageBody item={item} accent="green" />
			</Box>
		);
	}

	return (
		<MessagePanel accent="green" label={isStreaming ? 'assistant streaming' : 'assistant'} mood="(^_^)/">
			<MessageBody item={item} accent="green" />
		</MessagePanel>
	);
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

function MessageBody({
	item,
	accent,
}: {
	item: TranscriptItem;
	accent: 'cyan' | 'green' | 'yellow';
}): React.JSX.Element {
	return (
		<Box flexDirection="column">
			{item.text ? <Text color={accent === 'yellow' ? 'yellow' : undefined}>{item.text}</Text> : null}
			{item.attachments?.length ? (
				<Box flexDirection="column" marginTop={item.text ? 1 : 0}>
					<Text dimColor>attachments</Text>
					{item.attachments.map((attachment, index) => (
						<Text key={attachment.id} dimColor>{formatAttachmentLabel(attachment, index + 1)}</Text>
					))}
				</Box>
			) : null}
		</Box>
	);
}
