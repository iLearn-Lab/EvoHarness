import React, {useEffect, useMemo, useState} from 'react';
import {Box, useApp, useInput, useStdout} from 'ink';

import {CommandPicker} from './components/CommandPicker.js';
import {ConversationView} from './components/ConversationView.js';
import {ModalHost} from './components/ModalHost.js';
import {PromptInput} from './components/PromptInput.js';
import {SelectModal, type SelectOption} from './components/SelectModal.js';
import {StatusBar} from './components/StatusBar.js';
import {useBackendSession} from './hooks/useBackendSession.js';
import type {FrontendConfig, TranscriptItem} from './types.js';

const PERMISSION_MODES: SelectOption[] = [
	{value: 'default', label: 'Default', description: 'Ask before write/execute operations'},
	{value: 'full-auto', label: 'Auto', description: 'Allow all tools automatically'},
	{value: 'plan', label: 'Plan Mode', description: 'Block write operations'},
];

type SelectModalState = {
	title: string;
	options: SelectOption[];
	onSelect: (value: string) => void;
} | null;

export function App({config}: {config: FrontendConfig}): React.JSX.Element {
	const {exit} = useApp();
	const {stdout} = useStdout();
	const [input, setInput] = useState('');
	const [modalInput, setModalInput] = useState('');
	const [history, setHistory] = useState<string[]>([]);
	const [historyIndex, setHistoryIndex] = useState(-1);
	const [pickerIndex, setPickerIndex] = useState(0);
	const [selectModal, setSelectModal] = useState<SelectModalState>(null);
	const [selectIndex, setSelectIndex] = useState(0);
	const [expandedResultIds, setExpandedResultIds] = useState<string[]>([]);
	const [messageOffset, setMessageOffset] = useState(0);
	const [terminalSize, setTerminalSize] = useState({
		columns: stdout.columns ?? 100,
		rows: stdout.rows ?? 40,
	});
	const session = useBackendSession(config, () => exit());

	const currentToolName = useMemo(() => {
		for (let index = session.transcript.length - 1; index >= 0; index--) {
			const item = session.transcript[index];
			if (item.role === 'tool') {
				return item.tool_name ?? 'tool';
			}
			if (item.role === 'tool_result' || item.role === 'assistant') {
				break;
			}
		}
		return undefined;
	}, [session.transcript]);

	const commandHints = useMemo(() => {
		const value = input.trim();
		if (!value.startsWith('/') || value === '/') {
			return [] as string[];
		}
		return session.commands.filter((command) => command.startsWith(value)).slice(0, 10);
	}, [session.commands, input]);

	const showPicker = commandHints.length > 0 && !session.busy && !session.modal && !selectModal;

	const latestExpandableId = useMemo(() => {
		for (let index = session.transcript.length - 1; index >= 0; index--) {
			const item = session.transcript[index];
			if (isExpandableToolResult(item)) {
				return item.id;
			}
		}
		return undefined;
	}, [session.transcript]);

	useEffect(() => {
		const updateSize = (): void => {
			setTerminalSize({
				columns: stdout.columns ?? 100,
				rows: stdout.rows ?? 40,
			});
		};
		updateSize();
		stdout.on('resize', updateSize);
		return () => {
			stdout.off('resize', updateSize);
		};
	}, [stdout]);

	const conversationBudget = useMemo(() => {
		let reserved = 11;
		if (session.modal) {
			reserved += session.modal.kind === 'question' ? 6 : 7;
		}
		if (selectModal) {
			reserved += Math.min(selectModal.options.length, 6) + 4;
		}
		if (showPicker) {
			reserved += Math.min(commandHints.length, 6) + 4;
		}
		return Math.max(8, terminalSize.rows - reserved);
	}, [commandHints.length, selectModal, session.modal, showPicker, terminalSize.rows]);

	useEffect(() => {
		setPickerIndex(0);
	}, [commandHints.length, input]);

	useEffect(() => {
		setMessageOffset(0);
	}, [session.transcript.length]);

	useEffect(() => {
		if (!session.selectRequest) {
			return;
		}
		const request = session.selectRequest;
		if (request.options.length === 0) {
			session.setSelectRequest(null);
			return;
		}
		setSelectIndex(0);
		setSelectModal({
			title: request.title,
			options: request.options.map((option) => ({
				value: option.value,
				label: option.label,
				description: option.description,
			})),
			onSelect: (value) => {
				session.sendRequest({type: 'submit_line', line: `${request.submitPrefix}${value}`});
				session.setBusy(true);
				setSelectModal(null);
			},
		});
		session.setSelectRequest(null);
	}, [session.selectRequest]);

	const handleCommand = (command: string): boolean => {
		const trimmed = command.trim();
		if (trimmed === '/permissions' || trimmed === '/permissions show') {
			const currentMode = String(session.status.permission_mode ?? 'default');
			const options = PERMISSION_MODES.map((option) => ({
				...option,
				active: option.value === currentMode,
			}));
			const initialIndex = options.findIndex((option) => option.active);
			setSelectIndex(initialIndex >= 0 ? initialIndex : 0);
			setSelectModal({
				title: 'Permission Mode',
				options,
				onSelect: (value) => {
					session.sendRequest({type: 'submit_line', line: `/permissions ${value}`});
					session.setBusy(true);
					setSelectModal(null);
				},
			});
			return true;
		}
		if (trimmed === '/resume') {
			session.sendRequest({type: 'list_sessions'});
			return true;
		}
		return false;
	};

	useInput((chunk, key) => {
		if (key.ctrl && chunk === 'c') {
			session.sendRequest({type: 'shutdown'});
			session.setBusy(true);
			return;
		}

		if (selectModal) {
			if (key.upArrow) {
				setSelectIndex((index) => Math.max(0, index - 1));
				return;
			}
			if (key.downArrow) {
				setSelectIndex((index) => Math.min(selectModal.options.length - 1, index + 1));
				return;
			}
			if (key.return) {
				const selected = selectModal.options[selectIndex];
				if (selected) {
					selectModal.onSelect(selected.value);
				}
				return;
			}
			if (key.escape) {
				setSelectModal(null);
				return;
			}
			return;
		}

		if (session.modal?.kind === 'permission') {
			if (chunk.toLowerCase() === 'y') {
				session.sendRequest({
					type: 'permission_response',
					request_id: session.modal.request_id,
					allowed: true,
				});
				session.setModal(null);
				return;
			}
			if (chunk.toLowerCase() === 'n' || key.escape) {
				session.sendRequest({
					type: 'permission_response',
					request_id: session.modal.request_id,
					allowed: false,
				});
				session.setModal(null);
				return;
			}
			return;
		}

		if (session.busy) {
			return;
		}

		if (!showPicker && !session.modal && !selectModal && !input && latestExpandableId) {
			if (key.rightArrow) {
				setExpandedResultIds((items) => (items.includes(latestExpandableId) ? items : [...items, latestExpandableId]));
				return;
			}
			if (key.leftArrow) {
				setExpandedResultIds((items) => items.filter((item) => item !== latestExpandableId));
				return;
			}
		}

		if (!showPicker && !session.modal && !selectModal && !input) {
			if (key.pageUp || (key.ctrl && key.upArrow)) {
				setMessageOffset((value) => Math.min(value + 6, Math.max(0, session.transcript.length - 1)));
				return;
			}
			if (key.pageDown || (key.ctrl && key.downArrow)) {
				setMessageOffset((value) => Math.max(0, value - 6));
				return;
			}
		}

		if (showPicker) {
			if (key.upArrow) {
				setPickerIndex((index) => Math.max(0, index - 1));
				return;
			}
			if (key.downArrow) {
				setPickerIndex((index) => Math.min(commandHints.length - 1, index + 1));
				return;
			}
			if (key.return) {
				const selected = commandHints[pickerIndex];
				if (selected) {
					setInput('');
					if (!handleCommand(selected)) {
						onSubmit(selected);
					}
				}
				return;
			}
			if (key.tab) {
				const selected = commandHints[pickerIndex];
				if (selected) {
					setInput(selected + ' ');
				}
				return;
			}
			if (key.escape) {
				setInput('');
				return;
			}
		}

		if (!showPicker && key.upArrow) {
			const nextIndex = Math.min(history.length - 1, historyIndex + 1);
			if (nextIndex >= 0) {
				setHistoryIndex(nextIndex);
				setInput(history[history.length - 1 - nextIndex] ?? '');
			}
			return;
		}
		if (!showPicker && key.downArrow) {
			const nextIndex = Math.max(-1, historyIndex - 1);
			setHistoryIndex(nextIndex);
			setInput(nextIndex === -1 ? '' : (history[history.length - 1 - nextIndex] ?? ''));
			return;
		}
	});

	const onSubmit = (value: string): void => {
		if (session.modal?.kind === 'question') {
			session.sendRequest({
				type: 'question_response',
				request_id: session.modal.request_id,
				answer: value,
			});
			session.setModal(null);
			setModalInput('');
			return;
		}
		if (!value.trim() || session.busy) {
			return;
		}
		if (handleCommand(value)) {
			setHistory((items) => [...items, value]);
			setHistoryIndex(-1);
			setInput('');
			return;
		}
		session.sendRequest({type: 'submit_line', line: value});
		setHistory((items) => [...items, value]);
		setHistoryIndex(-1);
		setInput('');
		session.setBusy(true);
	};

	return (
		<Box flexDirection="column" paddingX={1} height="100%">
			<Box flexDirection="column" flexGrow={1}>
				<ConversationView
					items={session.transcript}
					assistantBuffer={session.assistantBuffer}
					showWelcome={true}
					status={session.status}
					maxVisibleLines={conversationBudget}
					terminalWidth={Math.max(40, terminalSize.columns - 4)}
					expandedResultIds={expandedResultIds}
					latestExpandableId={latestExpandableId}
					messageOffset={messageOffset}
				/>
			</Box>

			{session.modal ? (
				<ModalHost modal={session.modal} modalInput={modalInput} setModalInput={setModalInput} onSubmit={onSubmit} />
			) : null}

			{selectModal ? (
				<SelectModal title={selectModal.title} options={selectModal.options} selectedIndex={selectIndex} />
			) : null}

			{showPicker ? <CommandPicker hints={commandHints} selectedIndex={pickerIndex} /> : null}

			<StatusBar status={session.status} tasks={session.tasks} />

			{session.modal || selectModal ? null : (
				<PromptInput
					busy={session.busy}
					input={input}
					setInput={setInput}
					onSubmit={onSubmit}
					toolName={session.busy ? currentToolName : undefined}
					suppressSubmit={showPicker}
					hasExpandableResult={Boolean(latestExpandableId)}
					resultExpanded={Boolean(latestExpandableId && expandedResultIds.includes(latestExpandableId))}
				/>
			)}
		</Box>
	);
}

function isExpandableToolResult(item: TranscriptItem): boolean {
	if (item.role !== 'tool_result' || item.tool_name === 'run_subagent') {
		return false;
	}
	const lines = item.text.split('\n');
	return lines.length > 6 || item.text.length > 260;
}
