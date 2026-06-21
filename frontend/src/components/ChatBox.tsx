"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2, Send } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

export interface ChatBoxProps {
  onSubmit: (message: string) => void;
  pending?: boolean;
}

const schema = z.object({
  message: z.string().trim().min(1, "Enter a booking request to continue."),
});

type ChatForm = z.infer<typeof schema>;

/**
 * Single-field booking form using RHF register() so the textarea value is
 * read from the DOM element directly at submit time. This avoids relying on
 * React's synthetic onChange event, which is not reliably fired for
 * programmatic input (Playwright fill) in production Next.js builds.
 */
export function ChatBox({ onSubmit, pending }: ChatBoxProps) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<ChatForm>({
    resolver: zodResolver(schema),
    defaultValues: { message: "" },
  });

  return (
    <form
      onSubmit={handleSubmit((values) => onSubmit(values.message.trim()))}
      className="space-y-3"
    >
      <div className="space-y-2">
        <Label htmlFor="message">Booking message</Label>
        <Textarea
          id="message"
          placeholder="Describe the booking, e.g. 'Book a plumber for Tuesday 9am for Jane Doe'"
          rows={3}
          disabled={pending}
          className="resize-y"
          aria-describedby="message-desc"
          aria-invalid={!!errors.message}
          {...register("message")}
        />
        <p id="message-desc" className="text-[0.8rem] text-muted-foreground">
          Natural language — the agents extract the structured request.
        </p>
        {errors.message && (
          <p role="alert" className="text-[0.8rem] font-medium text-destructive">
            {errors.message.message}
          </p>
        )}
      </div>
      <Button type="submit" disabled={pending} className="w-full">
        {pending ? (
          <>
            <Loader2 className="animate-spin" aria-hidden="true" />
            Starting…
          </>
        ) : (
          <>
            <Send aria-hidden="true" />
            Submit
          </>
        )}
      </Button>
    </form>
  );
}
