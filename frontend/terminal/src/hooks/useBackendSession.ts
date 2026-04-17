import {useEffect, useMemo, useRef, useState} from 'react';
import {spawn, type ChildProcess} from 'node:child_process';
import readline from 'node:readline';

import type {AttachmentPayload, BackendEvent, FrontendConfig, SelectOptionPayload, TaskSnapshot, TranscriptItem} from '../types.js';

const PROTOCOL_PREFIX = 'EVOJSON:';
const MAX_LIVE_STREAM_CHARS = 120;
const STREAM_TAIL_CHARS = 72;
const STREAM_BOUNDARY_SEARCH_WINDOW = 96;

export function useBackendSession(config: FrontendConfig, onExit: (code?: number | null) => void) {
	const [transcript, setTranscript] = useState<TranscriptItem[]>([]);
	const [renderFeed, setRenderFeed] = useState<TranscriptItem[]>([]);
	const [assistantBuffer, setAssistantBuffer] = useState('');
	const [status, setStatus] = useState<Record<string, unknown>>({});
	const [tasks, setTasks] = useState<TaskSnapshot[]>([]);
	const [commands, setCommands] = useState<string[]>([]);
	const [modal, setModal] = useState<Record<string, unknown> | null>(null);
	const [selectRequest, setSelectRequest] = useState<{title: string; submitPrefix: string; options: SelectOptionPayload[]} | null>(null);
	const [pendingAttachments, setPendingAttachments] = useState<AttachmentPayload[]>([]);
	const [busy, setBusy] = useState(false);
	const childRef = useRef<ChildProcess | null>(null);
	const sentInitialPrompt = useRef(false);
	const assistantBufferRef = useRef('');
	const nextItemId = useRef(1);
	const assistantStreamChunkCountRef = useRef(0);

	useEffect(() => {
		assistantBufferRef.current = assistantBuffer;
	}, [assistantBuffer]);

	const withId = (item: TranscriptItem): TranscriptItem => ({
		id: item.id ?? `t${nextItemId.current++}`,
		...item,
	});

	const appendTranscriptItem = (item: TranscriptItem): void => {
		const normalized = withId(item);
		setTranscript((items) => [...items, normalized]);
		setRenderFeed((items) => [...items, normalized]);
	};

	const appendRenderFeedItem = (item: TranscriptItem): void => {
		const normalized = withId(item);
		setRenderFeed((items) => [...items, normalized]);
	};

	const appendAssistantStreamChunk = (text: string): void => {
		if (!text) {
			return;
		}
		const continuation = assistantStreamChunkCountRef.current > 0;
		appendRenderFeedItem({
			role: 'assistant',
			text,
			metadata: {
				streaming: true,
				continuation,
			},
		});
		assistantStreamChunkCountRef.current += 1;
	};

	const sendRequest = (payload: Record<string, unknown>): void => {
		const child = childRef.current;
		if (!child || !child.stdin || child.stdin.destroyed) {
			return;
		}
		child.stdin.write(JSON.stringify(payload) + '\n');
	};

	const handleEvent = (event: BackendEvent): void => {
		if (event.type === 'ready') {
			setStatus(event.state ?? {});
			setTasks(event.tasks ?? []);
			setCommands(event.commands ?? []);
			if (config.initial_prompt && !sentInitialPrompt.current) {
				sentInitialPrompt.current = true;
				sendRequest({type: 'submit_line', line: config.initial_prompt});
				setBusy(true);
			}
			return;
		}

		if (event.type === 'state_snapshot') {
			setStatus(event.state ?? {});
			return;
		}

		if (event.type === 'tasks_snapshot') {
			setTasks(event.tasks ?? []);
			return;
		}

		if (event.type === 'transcript_item' && event.item) {
			appendTranscriptItem(event.item as TranscriptItem);
			return;
		}

		if (event.type === 'transcript_reset') {
			const restoredItems = (event.items ?? []).map((item) => withId(item as TranscriptItem));
			setTranscript(restoredItems);
			setAssistantBuffer('');
			setPendingAttachments([]);
			assistantStreamChunkCountRef.current = 0;
			setRenderFeed((items) => {
				if (items.length === 0) {
					return [...restoredItems];
				}
				return [
					...items,
					withId({role: 'system', text: '----- session snapshot loaded below -----'}),
					...restoredItems,
				];
			});
			return;
		}

		if (event.type === 'attachment_added' && event.attachment) {
			setPendingAttachments((items) => [...items, event.attachment as AttachmentPayload]);
			return;
		}

		if (event.type === 'assistant_delta') {
			setAssistantBuffer((value) => {
				const combined = value + (event.message ?? '');
				const {flushText, remaining} = splitStreamingBuffer(combined);
				if (flushText) {
					appendAssistantStreamChunk(flushText);
				}
				return remaining;
			});
			return;
		}

		if (event.type === 'assistant_complete') {
			const text = event.message ?? assistantBufferRef.current;
			setTranscript((items) => [...items, withId({role: 'assistant', text})]);
			if (assistantStreamChunkCountRef.current > 0) {
				if (assistantBufferRef.current) {
					appendAssistantStreamChunk(assistantBufferRef.current);
				}
			} else {
				appendRenderFeedItem({role: 'assistant', text});
			}
			setAssistantBuffer('');
			assistantStreamChunkCountRef.current = 0;
			setBusy(false);
			return;
		}

		if (event.type === 'line_complete') {
			setBusy(false);
			return;
		}

		if ((event.type === 'tool_started' || event.type === 'tool_completed') && event.item) {
			appendTranscriptItem(event.item as TranscriptItem);
			return;
		}

		if (event.type === 'clear_transcript') {
			setTranscript([]);
			setAssistantBuffer('');
			setPendingAttachments([]);
			assistantStreamChunkCountRef.current = 0;
			setRenderFeed((items) =>
				items.length === 0
					? items
					: [...items, withId({role: 'system', text: '----- transcript cleared; older scrollback remains above -----'})],
			);
			return;
		}

		if (event.type === 'select_request') {
			const requestModal = event.modal ?? {};
			setSelectRequest({
				title: String(requestModal.title ?? 'Select'),
				submitPrefix: String(requestModal.submit_prefix ?? ''),
				options: event.select_options ?? [],
			});
			return;
		}

		if (event.type === 'modal_request') {
			setModal(event.modal ?? null);
			return;
		}

		if (event.type === 'error') {
			assistantStreamChunkCountRef.current = 0;
			appendTranscriptItem({role: 'system', text: `error: ${event.message ?? 'unknown error'}`});
			setBusy(false);
			return;
		}

		if (event.type === 'shutdown') {
			onExit(0);
		}
	};

	useEffect(() => {
		const [command, ...args] = config.backend_command;
		const child = spawn(command, args, {
			stdio: ['pipe', 'pipe', 'inherit'],
			env: process.env,
		});
		childRef.current = child;
		if (!child.stdout || !child.stdin) {
			appendTranscriptItem({role: 'system', text: 'backend stdio is unavailable'});
			onExit(1);
			return () => undefined;
		}

		child.stdin.setDefaultEncoding('utf8');
		child.stdout.setEncoding('utf8');
		const stdin = child.stdin;
		const reader = readline.createInterface({input: child.stdout});

		reader.on('line', (line) => {
			if (!line.startsWith(PROTOCOL_PREFIX)) {
				appendTranscriptItem({role: 'log', text: line});
				return;
			}
			const event = JSON.parse(line.slice(PROTOCOL_PREFIX.length)) as BackendEvent;
			handleEvent(event);
		});

		child.on('exit', (code) => {
			onExit(code);
		});

		return () => {
			reader.close();
			if (!child.killed) {
				child.kill();
			}
			if (!stdin.destroyed) {
				stdin.destroy();
			}
		};
	}, []);

	return useMemo(
		() => ({
			transcript,
			renderFeed,
			assistantBuffer,
			status,
			tasks,
			commands,
			modal,
			selectRequest,
			pendingAttachments,
			busy,
			setModal,
			setSelectRequest,
			setPendingAttachments,
			setBusy,
			sendRequest,
		}),
		[assistantBuffer, busy, commands, modal, pendingAttachments, renderFeed, selectRequest, status, tasks, transcript],
	);
}

function splitStreamingBuffer(buffer: string): {flushText: string; remaining: string} {
	if (!buffer) {
		return {flushText: '', remaining: ''};
	}

	const lastNewline = buffer.lastIndexOf('\n');
	if (lastNewline >= 0) {
		return {
			flushText: buffer.slice(0, lastNewline + 1),
			remaining: buffer.slice(lastNewline + 1),
		};
	}

	if (buffer.length <= MAX_LIVE_STREAM_CHARS) {
		return {flushText: '', remaining: buffer};
	}

	const splitTarget = Math.max(STREAM_TAIL_CHARS, buffer.length - STREAM_TAIL_CHARS);
	const splitAt = findStreamBoundary(buffer, splitTarget);
	return {
		flushText: buffer.slice(0, splitAt),
		remaining: buffer.slice(splitAt),
	};
}

function findStreamBoundary(text: string, fallbackIndex: number): number {
	const minIndex = Math.max(1, Math.min(fallbackIndex, text.length - 1));
	for (let index = minIndex; index > Math.max(1, minIndex - STREAM_BOUNDARY_SEARCH_WINDOW); index--) {
		if (isStreamBoundaryChar(text[index])) {
			return index + 1;
		}
	}
	for (let index = minIndex; index > Math.max(1, minIndex - STREAM_BOUNDARY_SEARCH_WINDOW); index--) {
		const char = text[index];
		if (char === ' ' || char === '\t') {
			return index + 1;
		}
	}
	return minIndex;
}

function isStreamBoundaryChar(char: string | undefined): boolean {
	if (!char) {
		return false;
	}

	return (
		char === '\n' ||
		char === '.' ||
		char === ',' ||
		char === '!' ||
		char === '?' ||
		char === ';' ||
		char === ':' ||
		char === '，' ||
		char === '。' ||
		char === '！' ||
		char === '？' ||
		char === '；' ||
		char === '：' ||
		char === '、' ||
		char === ')' ||
		char === '）'
	);
}
