import { render } from '@testing-library/react';
import { Icon } from './Icon';

test('renders an svg with the given size', () => {
  const { container } = render(<Icon name="lock" size={20} />);
  const svg = container.querySelector('svg')!;
  expect(svg.getAttribute('width')).toBe('20');
});

test('unknown icon name renders nothing', () => {
  const { container } = render(<Icon name={'nope' as never} />);
  expect(container.querySelector('svg')).toBeNull();
});
