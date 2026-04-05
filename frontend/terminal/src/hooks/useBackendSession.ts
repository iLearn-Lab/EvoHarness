import {useEffect, useMemo, useRef, useState} from 'react';
import {spawn, type ChildProcess} from 'node:child_process';
import readline from 'node:readline';

import type {BackendEvent, FrontendConfig, SelectOptionPayload, TaskSnapshot, TranscriptItem} from '../types.js';

const PROTOCOL_PREFIX = 'EVOJSON:';

export function useBackendSession(config: FrontendConfig, onExit: (code?: number | null) => void) {
	const [transcript, setTranscript] = useState<TranscriptItem[]>([]);
	const [assistantBuffer, setAssistantBuffer] = useState('');
	const [status, setStatus] = useState<Record<string, unknown>>({});
	const [tasks, setTasks] = useState<TaskSnapshot[]>([]);
	const [commands, setCommands] = useState<string[]>([]);
	const [modal, setModal] = useState<Record<string, unknown> | null>(null);
	const [selectRequest, setSelectRequest] = useState<{title: string; submitPrefix: string; options: SelectOptionPayload[]} | null>(null);
	const [busy, setBusy] = useState(false);
	const childRef = useRef<ChildProcess | null>(null);
	const sentInitialPrompt = useRef(false);
	const assistantBufferRef = useRef('');
	const nextItemId = useRef(1);

	useEffect(() => {
		assistantBufferRef.current = assistantBuffer;
	}, [assistantBuffer]);

	const withId = (item: TranscriptItem): TranscriptItem => ({
		id: item.id ?? `t${nextItemId.current++}`,
		...item,
	});

	const sendRequest = (payload: Record<string, unknown>): void => {
		const child = childRef.current;
		if (!child || !child.stdin || child.stdin.destroyed) {
			return;
		}
		child.stdin.write(JSON.stringify(payload) + '\n');
	};

	useEffect(() => {
		const [command, ...args] = config.backend_command;
		const child = spawn(command, args, {
			stdio: ['pipe', 'pipe', 'inherit'],
			env: process.env,
		});
		childRef.current = child;
		if (!child.stdout || !child.stdin) {
			setTranscript((items) => [...items, withId({role: 'system', text: 'backend stdio is unavailable'})]);
			onExit(1);
			return () => undefined;
		}
		child.stdin.setDefaultEncoding('utf8');
		child.stdout.setEncoding('utf8');
		const stdin = child.stdin;

		const reader = readline.createInterface({input: child.stdout});
		reader.on('line', (line) => {
			if (!line.startsWith(PROTOCOL_PREFIX)) {
				setTranscript((items) => [...items, withId({role: 'log', text: line})]);
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
			setTranscript((items) => [...items, withId(event.item as TranscriptItem)]);
			return;
		}
		if (event.type === 'assistant_delta') {
			setAssistantBuffer((value) => value + (event.message ?? ''));
			return;
		}
		if (event.type === 'assistant_complete') {
			const text = event.message ?? assistantBufferRef.current;
			setTranscript((items) => [...items, withId({role: 'assistant', text})]);
			setAssistantBuffer('');
			setBusy(false);
			return;
		}
		if (event.type === 'line_complete') {
			setBusy(false);
			return;
		}
		if ((event.type === 'tool_started' || event.type === 'tool_completed') && event.item) {
			setTranscript((items) => [...items, withId(event.item as TranscriptItem)]);
			return;
		}
		if (event.type === 'clear_transcript') {
			setTranscript([]);
			setAssistantBuffer('');
			return;
		}
		if (event.type === 'select_request') {
			const modal = event.modal ?? {};
			setSelectRequest({
				title: String(modal.title ?? 'Select'),
				submitPrefix: String(modal.submit_prefix ?? ''),
				options: event.select_options ?? [],
			});
			return;
		}
		if (event.type === 'modal_request') {
			setModal(event.modal ?? null);
			return;
		}
		if (event.type === 'error') {
			setTranscript((items) => [...items, withId({role: 'system', text: `error: ${event.message ?? 'unknown error'}`})]);
			setBusy(false);
			return;
		}
		if (event.type === 'shutdown') {
			onExit(0);
		}
	};

	return useMemo(
		() => ({
			transcript,
			assistantBuffer,
			status,
			tasks,
			commands,
			modal,
			selectRequest,
			busy,
			setModal,
			setSelectRequest,
			setBusy,
			sendRequest,
		}),
		[assistantBuffer, busy, commands, modal, selectRequest, status, tasks, transcript]
	);
}
