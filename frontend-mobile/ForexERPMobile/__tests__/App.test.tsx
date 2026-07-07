/**
 * @format
 */

import 'react-native';
import React from 'react';
import App from '../App';

// Note: import explicitly to use the types shipped with jest.
import {it} from '@jest/globals';

// Note: test renderer must be required after react-native.
import renderer, {act} from 'react-test-renderer';

it('renders correctly', async () => {
  // AuthProvider dispara un efecto asíncrono (lee AsyncStorage) que actualiza
  // el estado tras el primer render; se envuelve en act() y se espera para
  // evitar warnings y actualizaciones fuera del ciclo de vida del test.
  let tree: renderer.ReactTestRenderer | undefined;
  await act(async () => {
    tree = renderer.create(<App />);
  });
  act(() => {
    tree?.unmount();
  });
});
