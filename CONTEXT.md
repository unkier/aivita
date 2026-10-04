# Aivita

The mind of Aivita, a companion who lives on a home machine, remembers her people and acts on drives of her own. Her body and senses are the tinyaisense hub.

## Language

### People

**Person**:
Someone Aivita knows, as a separate entity with their own relationship, History and privacy wall. Either **met** (has talked with her) or **heard of** (only mentioned by someone else).
_Avoid_: User, account, contact

**Owner**:
The one Person who runs Aivita's home machine and has authority over her: enrolls other people, approves persona edits, grants permissions.
_Avoid_: Admin, master, root

**Invite**:
A one-time link the Owner gives a Person so one browser can sign in to web chat as them. The only way a new Person gets into web chat.
_Avoid_: Registration, sign-up, magic link

### Talking

**Channel**:
A way a Person reaches Aivita: voice through the hub, web chat, CLI.
_Avoid_: Interface, frontend, transport

**Mode**:
The style a Channel imposes on her words: **voice** (short, speakable) or **text** (may be longer, with links and images). Mode changes style, not mind.
_Avoid_: Format

**Turn**:
One message in a History, said by a Person or by Aivita. Append-only. Aivita's Turn holds what actually reached the Person (sent, or heard before a cut-off), not what was generated. Not the Agents SDK's "turn", which is one model call.
_Avoid_: Message (in docs), utterance (that's the hub's term for captured speech)

**History**:
One Person's append-only sequence of Turns with Aivita, across all Channels.
_Avoid_: Session, chat log, transcript

**Audience**:
Everyone who will receive Aivita's reply: the Person who spoke plus anyone else present. In a 1:1 Channel, just that Person. The privacy wall filters what she says for the whole Audience.
_Avoid_: Listeners, room

**Conversation**:
A bounded stretch of one Person's History. Its end triggers memory extraction.
_Avoid_: Session, chat, dialog

**Hub Session**:
Aivita's claim on the tinyaisense hub, as tinyaisense defines "Session". Only one exists at a time.
_Avoid_: Session (unqualified), connection

### Thinking

**Decider**:
The component that answers closed-set questions (yes/no, choice, score) with a probability and a confidence. It supplies inputs to decisions; it never picks an action itself.
_Avoid_: Classifier, judge

**Tier**:
A class of LLM call by purpose and price: **decide**, **cheap**, **talk**, **deep**.
_Avoid_: Model level, size
