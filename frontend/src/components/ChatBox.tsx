"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2, Send } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Textarea } from "@/components/ui/textarea";

export interface ChatBoxProps {
  onSubmit: (message: string) => void;
  pending?: boolean;
}

const schema = z.object({
  message: z.string().trim().min(1, "Enter a booking request to continue."),
});

type ChatForm = z.infer<typeof schema>;

/** Single-field form to submit a booking request message (RHF + zod). */
export function ChatBox({ onSubmit, pending }: ChatBoxProps) {
  const form = useForm<ChatForm>({
    resolver: zodResolver(schema),
    defaultValues: { message: "" },
    mode: "onSubmit",
  });

  const message = form.watch("message");

  const handleSubmit = form.handleSubmit((values) => {
    onSubmit(values.message.trim());
  });

  return (
    <Form {...form}>
      <form onSubmit={handleSubmit} className="space-y-3">
        <FormField
          control={form.control}
          name="message"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Booking message</FormLabel>
              <FormControl>
                <Textarea
                  placeholder="Describe the booking, e.g. 'Book a plumber for Tuesday 9am for Jane Doe'"
                  rows={3}
                  disabled={pending}
                  className="resize-y"
                  {...field}
                />
              </FormControl>
              <FormDescription>
                Natural language — the agents extract the structured request.
              </FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />
        <Button
          type="submit"
          disabled={pending || message.trim().length === 0}
          className="w-full"
        >
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
    </Form>
  );
}
