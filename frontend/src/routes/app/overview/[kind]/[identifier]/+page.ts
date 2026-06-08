import type { PageLoad } from './$types';

export const ssr = false;

export const load: PageLoad = ({ params }) => {
  return {
    kind: params.kind,
    identifier: params.identifier
  };
};
