import React from 'react';
import {Box, Text} from 'ink';
import TextInput from 'ink-text-input';

export function ModalHost({
	modal,
	modalInput,
	setModalInput,
	onSubmit,
}: {
	modal: Record<string, unknown> | null;
	modalInput: string;
	setModalInput: (value: string) => void;
	onSubmit: (value: string) => void;
}): React.JSX.Element | null {
	if (modal?.kind === 'permission') {
		return (
			<Box flexDirection="column" marginTop={1} borderStyle="round" borderColor="yellow" paddingX={1}>
				<Text bold color="yellow">approval required  ::  careful move {'( -_- )'}</Text>
				<Text>tool: {String(modal.tool_name ?? 'tool')}</Text>
				{modal.reason ? <Text dimColor>{String(modal.reason)}</Text> : null}
				{modal.file_path ? <Text dimColor>path: {String(modal.file_path)}</Text> : null}
				{modal.command ? <Text dimColor>command: {String(modal.command)}</Text> : null}
				<Text color="green">y allow</Text>
				<Text color="red">n deny</Text>
			</Box>
		);
	}
	if (modal?.kind === 'question') {
		return (
			<Box flexDirection="column" marginTop={1} borderStyle="round" borderColor="magenta" paddingX={1}>
				<Text bold color="magenta">question  ::  {String(modal.question ?? 'Question')}</Text>
				<Box>
					<Text color="cyan">{'» '}</Text>
					<TextInput value={modalInput} onChange={setModalInput} onSubmit={onSubmit} />
				</Box>
			</Box>
		);
	}
	return null;
}
