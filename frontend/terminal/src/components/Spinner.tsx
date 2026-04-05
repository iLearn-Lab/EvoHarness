import React, {useEffect, useState} from 'react';
import {Text} from 'ink';

const FRAMES = ['|', '/', '-', '\\'];

export function Spinner({label}: {label?: string}): React.JSX.Element {
	const [frame, setFrame] = useState(0);

	useEffect(() => {
		const timer = setInterval(() => {
			setFrame((value) => (value + 1) % FRAMES.length);
		}, 90);
		return () => clearInterval(timer);
	}, []);

	return (
		<Text>
			<Text color="cyan">{FRAMES[frame]}</Text>
			<Text dimColor> {label ?? 'working'} (^_^)/</Text>
		</Text>
	);
}
