import React from 'react';
import {Box, Text} from 'ink';
import TextInput from 'ink-text-input';

import {Spinner} from './Spinner.js';

const noop = (): void => {};

export function PromptInput({
	busy,
	input,
	setInput,
	onSubmit,
	toolName,
	suppressSubmit,
	hasExpandableResult,
	resultExpanded,
}: {
	busy: boolean;
	input: string;
	setInput: (value: string) => void;
	onSubmit: (value: string) => void;
	toolName?: string;
	suppressSubmit?: boolean;
	hasExpandableResult?: boolean;
	resultExpanded?: boolean;
}): React.JSX.Element {
	if (busy) {
		return (
			<Box marginTop={1} borderStyle="round" borderColor="cyan" paddingX={1}>
				<Spinner label={toolName ? `running ${toolName}` : 'thinking'} />
			</Box>
		);
	}

	return (
		<Box flexDirection="column" marginTop={1} borderStyle="round" borderColor="cyan" paddingX={1}>
			<Text color="gray">compose  ::  say it cleanly \(^o^)/</Text>
			<Box>
				<Text color="cyan" bold>{'>> '}</Text>
				<TextInput value={input} onChange={setInput} onSubmit={suppressSubmit ? noop : onSubmit} />
			</Box>
			<Text dimColor>
				enter send  •  up/down history  •  tab complete slash commands
				{hasExpandableResult ? `  •  ${resultExpanded ? 'left fold latest result' : 'right expand latest result'}` : ''}
				{'  •  page up/down scroll transcript'}
			</Text>
		</Box>
	);
}
