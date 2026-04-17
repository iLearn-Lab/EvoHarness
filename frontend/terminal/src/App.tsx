import React, {useEffect, useMemo, useRef, useState} from 'react';
import {Box, useApp, useInput} from 'ink';

import {captureClipboardImage} from './clipboard.js';
import {CommandPicker} from './components/CommandPicker.js';
import {ConversationView} from './components/ConversationView.js';
import {ModalHost} from './components/ModalHost.js';
import {PromptInput} from './components/PromptInput.js';
import {SelectModal, type SelectOption} from './components/SelectModal.js';
import {StatusBar} from './components/StatusBar.js';
import {useBackendSession} from './hooks/useBackendSession.js';
import type {FrontendConfig} from './types.js';

const PERMISSION_MODES: SelectOption[] = [
	{value: 'default', label: 'Default', description: 'Ask before write or execute operations'},
	{value: 'full-access', label: 'Full Access', description: 'Allow broader shell and mutating actions automatically'},
	{value: 'plan', label: 'Plan Mode', description: 'Block write operations'},
];

const EVOLUTION_MODES: SelectOption[] = [
	{value: 'off', label: 'Off', description: 'Do not auto-run self-evolution after a session'},
	{value: 'candidate', label: 'Candidate', description: 'Generate candidates only, do not mutate the workspace'},
	{value: 'auto', label: 'Auto', description: 'Let the executor decide how far to advance the evolution'},
	{value: 'apply', label: 'Apply', description: 'Write changes into the workspace automatically'},
	{value: 'promote', label: 'Promote', description: 'Write and treat the result as a promoted evolution'},
];

const ALT_SEQUENCE_WINDOW_MS = 80;

type SelectModalState = {
	title: string;
	options: SelectOption[];
	onSelect: (value: string) => void;
} | null;

export function App({config}: {config: FrontendConfig}): React.JSX.Element {
	const {exit} = useApp();
	const [input, setInput] = useState('');
	const [modalInput, setModalInput] = useState('');
	const [history, setHistory] = useState<string[]>([]);
	const [historyIndex, setHistoryIndex] = useState(-1);
	const [pickerIndex, setPickerIndex] = useState(0);
	const [selectModal, setSelectModal] = useState<SelectModalState>(null);
	const [selectIndex, setSelectIndex] = useState(0);
	const [pastingImage, setPastingImage] = useState(false);
	const [pasteError, setPasteError] = useState<string | null>(null);
	const pendingEscapeActionRef = useRef<(() => void) | null>(null);
	const pendingEscapeTimerRef = useRef<NodeJS.Timeout | null>(null);
	const suppressShortcutTextRef = useRef(false);
	const session = useBackendSession(config, () => exit());

	const clearPendingEscapeAction = (): void => {
		if (pendingEscapeTimerRef.current) {
			clearTimeout(pendingEscapeTimerRef.current);
			pendingEscapeTimerRef.current = null;
		}
		pendingEscapeActionRef.current = null;
	};

	const scheduleEscapeAction = (action: () => void): void => {
		clearPendingEscapeAction();
		pendingEscapeActionRef.current = action;
		pendingEscapeTimerRef.current = setTimeout(() => {
			const pending = pendingEscapeActionRef.current;
			clearPendingEscapeAction();
			pending?.();
		}, ALT_SEQUENCE_WINDOW_MS);
	};

	const flushPendingEscapeAction = (): void => {
		const pending = pendingEscapeActionRef.current;
		if (!pending) {
			return;
		}
		clearPendingEscapeAction();
		pending();
	};

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
		const localCommands = ['/permissions', '/evo-mode', '/resume'];
		const merged = [...new Set([...localCommands, ...session.commands])];
		return merged.filter((command) => command.startsWith(value)).slice(0, 10);
	}, [session.commands, input]);

	const showPicker = commandHints.length > 0 && !session.busy && !session.modal && !selectModal;

	useEffect(() => {
		setPickerIndex(0);
	}, [commandHints.length, input]);

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

	useEffect(
		() => () => {
			clearPendingEscapeAction();
		},
		[],
	);

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

		if (trimmed === '/evo-mode' || trimmed === '/evo-mode show') {
			const currentMode = String(
				session.status.auto_self_evolution_enabled ? (session.status.auto_self_evolution_mode ?? 'candidate') : 'off',
			);
			const options = EVOLUTION_MODES.map((option) => ({
				...option,
				active: option.value === currentMode,
			}));
			const initialIndex = options.findIndex((option) => option.active);
			setSelectIndex(initialIndex >= 0 ? initialIndex : 0);
			setSelectModal({
				title: 'Evolution Mode',
				options,
				onSelect: (value) => {
					session.sendRequest({type: 'submit_line', line: `/evo-mode ${value}`});
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

	const removeLastPendingAttachment = (): void => {
		const last = session.pendingAttachments[session.pendingAttachments.length - 1];
		if (!last) {
			return;
		}
		session.sendRequest({type: 'discard_attachment', attachment_id: last.id});
		session.setPendingAttachments((items) => items.filter((item) => item.id !== last.id));
	};

	const pasteImage = async (): Promise<void> => {
		if (session.busy || session.modal || selectModal || pastingImage) {
			return;
		}

		setPasteError(null);
		setPastingImage(true);

		try {
			const capture = await captureClipboardImage();
			session.sendRequest({
				type: 'import_attachment',
				source_path: capture.path,
				file_name: capture.fileName,
				mime_type: capture.mimeType,
				source: capture.source,
				delete_source: true,
			});
		} catch (error) {
			const message = error instanceof Error ? error.message : String(error);
			setPasteError(message);
		} finally {
			setPastingImage(false);
		}
	};

	const handleInputChange = (nextValue: string): void => {
		if (suppressShortcutTextRef.current) {
			suppressShortcutTextRef.current = false;
			if (isShortcutArtifact(nextValue, input)) {
				return;
			}
		}

		setInput(nextValue);
	};

	useInput((chunk, key) => {
		const normalized = chunk.toLowerCase();
		const hasPendingEscapeAction = Boolean(pendingEscapeActionRef.current);

		if (key.ctrl && chunk === 'c') {
			clearPendingEscapeAction();
			session.sendRequest({type: 'shutdown'});
			session.setBusy(true);
			return;
		}

		if (isPasteShortcut(chunk, key, hasPendingEscapeAction)) {
			clearPendingEscapeAction();
			suppressShortcutTextRef.current = true;
			void pasteImage();
			return;
		}

		if (hasPendingEscapeAction) {
			flushPendingEscapeAction();
			return;
		}

		if (key.escape) {
			if (selectModal) {
				scheduleEscapeAction(() => {
					setSelectModal(null);
				});
				return;
			}

			if (session.modal?.kind === 'permission') {
				const requestId = session.modal.request_id;
				scheduleEscapeAction(() => {
					session.sendRequest({
						type: 'permission_response',
						request_id: requestId,
						allowed: false,
					});
					session.setModal(null);
				});
				return;
			}

			if (showPicker) {
				scheduleEscapeAction(() => {
					setInput('');
				});
				return;
			}
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
			return;
		}

		if (session.modal?.kind === 'permission') {
			if (normalized === 'y') {
				session.sendRequest({
					type: 'permission_response',
					request_id: session.modal.request_id,
					allowed: true,
				});
				session.setModal(null);
				return;
			}
			if (normalized === 'n' || key.escape) {
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
		}

		if (!showPicker && key.ctrl && normalized === 'p') {
			const nextIndex = Math.min(history.length - 1, historyIndex + 1);
			if (nextIndex >= 0) {
				setHistoryIndex(nextIndex);
				setInput(history[history.length - 1 - nextIndex] ?? '');
			}
			return;
		}

		if (!showPicker && key.ctrl && normalized === 'n') {
			const nextIndex = Math.max(-1, historyIndex - 1);
			setHistoryIndex(nextIndex);
			setInput(nextIndex === -1 ? '' : (history[history.length - 1 - nextIndex] ?? ''));
			return;
		}

		if (!showPicker && !input && session.pendingAttachments.length > 0 && (key.backspace || key.delete)) {
			removeLastPendingAttachment();
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

		if ((!value.trim() && session.pendingAttachments.length === 0) || session.busy || pastingImage) {
			return;
		}

		if (session.pendingAttachments.length > 0 && value.trim().startsWith('/')) {
			setPasteError('Attachments cannot be sent with slash commands.');
			return;
		}

		if (handleCommand(value)) {
			setHistory((items) => [...items, value]);
			setHistoryIndex(-1);
			setInput('');
			return;
		}

		setPasteError(null);
		session.sendRequest({
			type: 'submit_message',
			text: value,
			attachments: session.pendingAttachments,
		});
		if (value.trim()) {
			setHistory((items) => [...items, value]);
		}
		setHistoryIndex(-1);
		setInput('');
		session.setPendingAttachments([]);
		session.setBusy(true);
	};

	return (
		<Box flexDirection="column" paddingX={1} height="100%">
			<Box flexDirection="column" flexGrow={1}>
				<ConversationView
					items={session.renderFeed}
					assistantBuffer={session.assistantBuffer}
					showWelcome={true}
					status={session.status}
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
					pendingAttachments={session.pendingAttachments}
					pastingImage={pastingImage}
					pasteError={pasteError}
					setInput={handleInputChange}
					onSubmit={onSubmit}
					toolName={session.busy ? currentToolName : undefined}
					suppressSubmit={showPicker}
				/>
			)}
		</Box>
	);
}

function isPasteShortcut(chunk: string, key: {ctrl: boolean; meta: boolean}, hasPendingEscapeAction: boolean): boolean {
	const normalized = chunk.toLowerCase();
	return (
		chunk === '\u0016' ||
		(key.ctrl && normalized === 'v') ||
		(key.meta && normalized === 'v') ||
		(hasPendingEscapeAction && normalized === 'v')
	);
}

function isShortcutArtifact(nextValue: string, previousValue: string): boolean {
	if (nextValue.length !== previousValue.length + 1) {
		return false;
	}

	for (let index = 0; index < nextValue.length; index++) {
		const candidate = nextValue[index];
		if (!candidate) {
			continue;
		}
		if (candidate !== '\u0016' && candidate.toLowerCase() !== 'v') {
			continue;
		}
		const withoutCandidate = nextValue.slice(0, index) + nextValue.slice(index + 1);
		if (withoutCandidate === previousValue) {
			return true;
		}
	}

	return false;
}
