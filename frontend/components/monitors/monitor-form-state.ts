export type SubmitState = {
  error: string;
  submitting: boolean;
};

export function toggleSelectedValue(values: string[], value: string) {
  return values.includes(value) ? values.filter((item) => item !== value) : [...values, value];
}

export function startFormSubmit<T extends SubmitState>(state: T): T {
  return { ...state, error: '', submitting: true };
}

export function failFormSubmit<T extends SubmitState>(state: T, message: string): T {
  return { ...state, error: message };
}

export function settleFormSubmit<T extends SubmitState>(state: T): T {
  return { ...state, submitting: false };
}
