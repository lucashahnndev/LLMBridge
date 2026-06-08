<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';

  onMount(() => {
    void goto('/login');
  });
</script>

<svelte:head>
  <title>LLMKeyRotator</title>
  <meta name="description" content="Redirecting to the admin login." />
</svelte:head>

<main class="redirect-screen">
  <div class="redirect-card">
    <span class="eyebrow">LLMKeyRotator</span>
    <h1>Opening the admin console</h1>
    <p>Redirecting to the login screen.</p>
    <a href="/login">Continue to login</a>
  </div>
</main>
