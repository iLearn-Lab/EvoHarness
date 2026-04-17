import React from 'react';
import {Box, Text} from 'ink';
import TextInput from 'ink-text-input';

import {formatAttachmentLabel} from '../attachmentUtils.js';
import type {AttachmentPayload} from '../types.js';
import {Spinner} from './Spinner.js';

const noop = (): void => {};

export function PromptInput({
	busy,
	input,
	pendingAttachments,
	pastingImage,
	pasteError,
	setInput,
	onSubmit,
	toolName,
	suppressSubmit,
}: {
	busy: boolean;
	input: string;
	pendingAttachments: AttachmentPayload[];
	pastingImage?: boolean;
	pasteError?: string | null;
	setInput: (value: string) => void;
	onSubmit: (value: string) => void;
	toolName?: string;
	suppressSubmit?: boolean;
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
			<Text color="gray">compose :: native terminal scrollback is on :: say it cleanly (^o^)/</Text>
			{pendingAttachments.length > 0 ? (
				<Box flexDirection="column" marginBottom={1}>
					<Text color="cyan">attachments</Text>
					{pendingAttachments.map((attachment, index) => (
						<Text key={attachment.id} dimColor>{formatAttachmentLabel(attachment, index + 1)}</Text>
					))}
				</Box>
			) : null}
			{pastingImage ? <Text color="yellow">capturing clipboard image...</Text> : null}
			{pasteError ? <Text color="red">{pasteError}</Text> : null}
			<Box>
				<Text color="cyan" bold>{'>> '}</Text>
				<TextInput value={input} focus={true} onChange={setInput} onSubmit={suppressSubmit ? noop : onSubmit} />
			</Box>
			<Text dimColor>
				enter send  ::  ctrl+p/ctrl+n history  ::  tab complete slash commands  ::  use mouse wheel or terminal scrollback to browse history
				{'  ::  ctrl+v or alt+v paste image  ::  backspace remove last image  ::  /evo-mode'}
			</Text>
		</Box>
	);
}
